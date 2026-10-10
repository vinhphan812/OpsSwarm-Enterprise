import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import type { ProductInventory } from "@/types/twin.type";
import { stockState } from "./fixtureStock";

export type ProductRow = ProductInventory & { state: StockState };

/** Out of stock first, then low, then the rest; by SKU within each. */
const STATE_ORDER: Record<StockState, number> = { [STOCK_STATE.Out]: 0, [STOCK_STATE.Low]: 1, [STOCK_STATE.Ok]: 2 };

/** The store's products with their stock state, the ones that need attention first. */
export function productRows(products: ProductInventory[]): ProductRow[] {
  return products
    .map((product) => ({
      ...product,
      state: stockState({ facings: product.facings, shelfQuantity: product.shelf_quantity }),
    }))
    .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || a.sku.localeCompare(b.sku));
}

/** Rows whose SKU, shelf, or slot contains `query`, ignoring case. */
export function matchRows(rows: ProductRow[], query: string): ProductRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    [row.sku, row.shelf_id, row.slot_id].some((field) => field.toLowerCase().includes(needle)),
  );
}
