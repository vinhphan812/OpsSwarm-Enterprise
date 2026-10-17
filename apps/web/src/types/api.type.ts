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
};
