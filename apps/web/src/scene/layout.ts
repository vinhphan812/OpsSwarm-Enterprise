import type { ProductFixture, StoreFixture } from "@/types/scene.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type { ProductIssue } from "@/core/api/validate";
import { storeFixture } from "@/fixtures/storeFixture";

/**
 * Shelf, slot, and equipment positions. The twin state has no geometry yet, so the
 * layout is static in the web app (docs/adr/0006). Product placement comes from state.
 */
export const storeLayout: StoreFixture = storeFixture;

/** Slot ids of every fixture that holds products, by fixture id. */
const SLOTS_BY_HOLDER = new Map<string, Set<string>>(
  [
    ...storeLayout.shelves.map(
      (shelf) => [shelf.shelfId, shelf.slots] as const,
    ),
    ...storeLayout.equipment.map(
      (item) => [item.equipmentId, item.slots] as const,
    ),
  ]
    .filter(([, slots]) => slots.length > 0)
    .map(([id, slots]) => [id, new Set(slots.map((slot) => slot.slotId))]),
);

type SceneState = {
  store: StoreFixture;
  /** Products the layout cannot place; they are not drawn. */
  issues: ProductIssue[];
};

/** Why a product cannot go where the state puts it, or null when it can. */
function placementProblem(
  product: ProductFixture,
  taken: Map<string, string>,
): ProductIssue | null {
  const { productId: sku, shelfId, slotId } = product;
  const slots = SLOTS_BY_HOLDER.get(shelfId);
  if (!slots) return { sku, code: "unknownShelf", values: { shelfId } };
  if (!slots.has(slotId))
    return { sku, code: "slotNotOnShelf", values: { slotId, shelfId } };
  const owner = taken.get(slotId);
  if (owner) return { sku, code: "slotTaken", values: { slotId, owner } };
  return null;
}

/** API product records as scene products. Placement, facings, and stock come from state. */
function toProductFixtures(products: ProductInventory[]): ProductFixture[] {
  return products.map((product) => ({
    productId: product.sku,
    shelfId: product.shelf_id,
    slotId: product.slot_id,
    facings: product.facings,
    shelfQuantity: product.shelf_quantity,
    backroomQuantity: product.backroom_quantity,
    version: product.version,
  }));
}

/** Maps twin state onto the fixed layout. Placement, facings, and stock come from state. */
export function toSceneStore(state: StoreResponse): SceneState {
  const products: ProductFixture[] = [];
  const issues: ProductIssue[] = [];
  const taken = new Map<string, string>();
  for (const product of toProductFixtures(state.products)) {
    const problem = placementProblem(product, taken);
    if (problem) {
      issues.push(problem);
      continue;
    }
    taken.set(product.slotId, product.productId);
    products.push(product);
  }
  return {
    store: {
      storeId: state.store_id,
      shelves: storeLayout.shelves,
      equipment: storeLayout.equipment,
      products,
    },
    issues,
  };
}

const scenes = new WeakMap<StoreResponse, SceneState>();

/** `toSceneStore`, computed once per state object so every reader shares the result. */
export function sceneOf(state: StoreResponse): SceneState {
  let scene = scenes.get(state);
  if (!scene) {
    scene = toSceneStore(state);
    scenes.set(state, scene);
  }
  return scene;
}
