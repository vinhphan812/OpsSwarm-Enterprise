import type { RevenuePeriod } from "@/enums/commerce.enum";
import type { PromotionsSummary } from "./promotion.type";
import type { RevenueSummary } from "./revenue.type";
import type { ReviewDecision } from "@/enums/simulation.enum";
import type { CandidatesResponse, ReviewRequest, ReviewResult, Simulation, SimulationsResponse } from "./simulation.type";
import type { ProductInventory, StoreResponse } from "./twin.type";

export type HealthResponse = {
  status: "ok" | "degraded";
  service: "retailtwin-api";
  environment: string;
  store_id: string;
  fixture_loaded: boolean;
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
};
