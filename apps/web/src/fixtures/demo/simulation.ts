import { ACTION_TYPE, SIMULATION_STATUS } from "@/enums/simulation.enum";
import type { Simulation, SimulationAction } from "@/types/simulation.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Simulation Twin truth.
 * A simulation run on the demo store, as `GET /simulations/{id}` will serve it. Its
 * proposed state is worked out here only because apps/api serves no simulations yet.
 */

export const DEMO_SIMULATION_ID = "sim-demo-001";

/**
 * Restock the empty P003, give P004 one more facing, move P007 two slots along, and move
 * the well-stocked P008 and P005 to another gondola, so a move shows a full facing travel.
 */
export const DEMO_ACTIONS: SimulationAction[] = [
  { type: ACTION_TYPE.ReplenishShelf, sku: "P003", quantity: 12 },
  { type: ACTION_TYPE.ChangeFacings, sku: "P004", facings: 4 },
  { type: ACTION_TYPE.MoveProduct, sku: "P007", from_slot: "B02-S20", to_slot: "B02-S22" },
  { type: ACTION_TYPE.MoveProduct, sku: "P008", from_slot: "C01-S21", to_slot: "A02-S22" },
  { type: ACTION_TYPE.MoveProduct, sku: "P005", from_slot: "A03-S22", to_slot: "B01-S22" },
];

/** Slot ids are `<fixture id>-S<n>`, so the fixture of a slot is everything before the last dash. */
const holderOf = (slotId: string) => slotId.slice(0, slotId.lastIndexOf("-"));

function apply(product: ProductInventory, action: SimulationAction): ProductInventory {
  switch (action.type) {
    case ACTION_TYPE.ReplenishShelf: {
      const quantity = Math.min(action.quantity, product.backroom_quantity);
      return {
        ...product,
        shelf_quantity: product.shelf_quantity + quantity,
        backroom_quantity: product.backroom_quantity - quantity,
      };
    }
    case ACTION_TYPE.ChangeFacings:
      return { ...product, facings: action.facings };
    case ACTION_TYPE.MoveProduct:
      return { ...product, shelf_id: holderOf(action.to_slot), slot_id: action.to_slot };
  }
}

/** A simulation of `actions` on `base`. A new object per call; `base` is left as it is. */
export function simulationOf(
  base: StoreResponse,
  actions: SimulationAction[],
  simulationId = DEMO_SIMULATION_ID,
): Simulation {
  const products = base.products.map((product) =>
    actions.reduce(
      (next, action) => (action.sku === next.sku ? apply(next, action) : next),
      { ...product, version: product.version + (actions.some((action) => action.sku === product.sku) ? 1 : 0) },
    ),
  );
  return {
    simulation_id: simulationId,
    store_id: base.store_id,
    base_context_version: base.context_version,
    status: SIMULATION_STATUS.Evaluated,
    actions: structuredClone(actions),
    state: { ...structuredClone(base), products },
  };
}

/** The demo simulation on the demo store. */
export function demoSimulation(base: StoreResponse = demoStoreState()): Simulation {
  return simulationOf(base, DEMO_ACTIONS);
}
