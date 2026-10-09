import fixture from "../../../../data/schemas/store-state.example.json";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { contextRevision } from "@/core/api/version";

/**
 * `GET /store` for tests: the API's day-0 fixture (P001 on A01-S01) shaped the way
 * apps/api serves it, plus a neighbour on the same shelf and loose fruit on a produce
 * rack. Test data only; the app shows no products until the API sends them.
 */
export function sampleStoreState(): StoreResponse {
  const version = contextRevision(fixture.version) ?? 0;
  const p001: ProductInventory = { ...fixture.products[0], store_id: fixture.store_id, version };
  const product = (change: Partial<ProductInventory>): ProductInventory => ({ ...p001, ...change });
  return {
    store_id: fixture.store_id,
    context_version: `${fixture.store_id}:${fixture.version}`,
    version: fixture.version,
    products: [
      p001,
      product({ sku: "P002", slot_id: "A01-S02", facings: 2, shelf_quantity: 10, backroom_quantity: 5 }),
      product({ sku: "P003", shelf_id: "PR01", slot_id: "PR01-S01", facings: 4, shelf_quantity: 30, backroom_quantity: 60 }),
    ],
  };
}
