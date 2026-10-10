import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import { sceneOf, storeLayout } from "@/scene/layout";
import type { ProductFixture } from "@/types/scene.type";
import type { StoreResponse } from "@/types/twin.type";

export type FixtureProduct = Pick<
  ProductFixture,
  "productId" | "slotId" | "facings" | "shelfQuantity" | "backroomQuantity"
> & { state: StockState };

/** What the twin says is on one shelf or piece of equipment, summed up for its card. */
export type FixtureStock = {
  fixtureId: string;
  slotCount: number;
  /** Placed products, in slot order. */
  products: FixtureProduct[];
  unitsOnShelf: number;
  unitsInBackroom: number;
  lowCount: number;
  outCount: number;
};

/** Out with nothing on the shelf, low with fewer units than facings to fill. */
export function stockState(product: Pick<ProductFixture, "facings" | "shelfQuantity">): StockState {
  if (product.shelfQuantity <= 0) return STOCK_STATE.Out;
  if (product.shelfQuantity < product.facings) return STOCK_STATE.Low;
  return STOCK_STATE.Ok;
}

const SLOTS = new Map(
  [...storeLayout.shelves.map((shelf) => [shelf.shelfId, shelf.slots] as const),
    ...storeLayout.equipment.map((item) => [item.equipmentId, item.slots] as const)],
);

/**
 * The stock of `fixtureId` in the live state. Null for a fixture the layout does not
 * have. Only placed products count; ones the scene left out are listed as issues.
 */
export function fixtureStock(fixtureId: string, live: StoreResponse): FixtureStock | null {
  const slots = SLOTS.get(fixtureId);
  if (!slots) return null;
  const order = new Map(slots.map((slot, index) => [slot.slotId, index]));
  const products = sceneOf(live)
    .store.products.filter((product) => product.shelfId === fixtureId)
    .sort((a, b) => (order.get(a.slotId) ?? 0) - (order.get(b.slotId) ?? 0))
    .map(({ productId, slotId, facings, shelfQuantity, backroomQuantity }) => ({
      productId,
      slotId,
      facings,
      shelfQuantity,
      backroomQuantity,
      state: stockState({ facings, shelfQuantity }),
    }));
  return {
    fixtureId,
    slotCount: slots.length,
    products,
    unitsOnShelf: products.reduce((sum, product) => sum + product.shelfQuantity, 0),
    unitsInBackroom: products.reduce((sum, product) => sum + product.backroomQuantity, 0),
    lowCount: products.filter((product) => product.state === STOCK_STATE.Low).length,
    outCount: products.filter((product) => product.state === STOCK_STATE.Out).length,
  };
}

/** A shelf or piece of equipment of the layout, by id. */
export function findFixture(fixtureId: string) {
  const shelf = storeLayout.shelves.find((item) => item.shelfId === fixtureId);
  if (shelf) return { shelf, equipment: undefined } as const;
  const equipment = storeLayout.equipment.find((item) => item.equipmentId === fixtureId);
  return equipment ? ({ shelf: undefined, equipment } as const) : null;
}
