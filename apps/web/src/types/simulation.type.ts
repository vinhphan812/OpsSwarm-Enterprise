import type { ACTION_TYPE, SimulationStatus } from "@/enums/simulation.enum";
import type { StoreResponse } from "./twin.type";

export type MoveProductAction = {
  type: typeof ACTION_TYPE.MoveProduct;
  sku: string;
  from_slot: string;
  to_slot: string;
};

export type ChangeFacingsAction = {
  type: typeof ACTION_TYPE.ChangeFacings;
  sku: string;
  facings: number;
};

export type ReplenishShelfAction = {
  type: typeof ACTION_TYPE.ReplenishShelf;
  sku: string;
  quantity: number;
};

/** One proposed change; `ActionUnion` in contracts/TECHNICAL_SPEC.md. */
export type SimulationAction = MoveProductAction | ChangeFacingsAction | ReplenishShelfAction;

/**
 * A Simulation Twin run, as `GET /simulations/{simulation_id}` will serve it.
 * TODO(BE): apps/api serves no simulations yet; this shape is the FE's proposal (#26).
 */
export type Simulation = {
  simulation_id: string;
  store_id: string;
  /** Live state the simulation started from, as `StoreResponse.context_version`. */
  base_context_version: string;
  status: SimulationStatus;
  actions: SimulationAction[];
  /** The proposed store: Live at `base_context_version` with `actions` applied. Never Live truth. */
  state: StoreResponse;
};

/** One row of `GET /simulations?status=open`. TODO(BE): FE proposal (#26). */
export type SimulationSummary = Pick<Simulation, "simulation_id" | "store_id" | "base_context_version" | "status">;

/** `GET /simulations?status=open`. TODO(BE): FE proposal (#26). */
export type SimulationsResponse = { simulations: SimulationSummary[] };
