import type { ProductInventory } from "@/core/api/types";
import type { ProductFixture } from "./types";

/** API product records as scene products. Placement, facings, and stock come from state. */
export function toProductFixtures(products: ProductInventory[]): ProductFixture[] {
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
