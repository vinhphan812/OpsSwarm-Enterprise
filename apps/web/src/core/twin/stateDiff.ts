import type { ProductInventory, StoreResponse } from "@/types/twin.type";

export type SlotRef = { shelf_id: string; slot_id: string };

export type ProductMove = { sku: string; from: SlotRef; to: SlotRef };
export type FacingsChange = { sku: string; before: number; after: number };
/** Signed changes: `shelfDelta: 12, backroomDelta: -12` is a replenishment of 12. */
export type QuantityChange = { sku: string; shelfDelta: number; backroomDelta: number };

/**
 * What changed from one twin state to the next, per SKU and sorted by SKU. A product can
 * appear in several lists at once, such as a move that also changes its facings.
 */
export type StateDiff = {
  moved: ProductMove[];
  facings: FacingsChange[];
  quantity: QuantityChange[];
  /** SKUs only in the next state. */
  added: string[];
  /** SKUs only in the previous state. */
  removed: string[];
};

/** A diff with no changes. Shared, so never mutate it. */
export const EMPTY_DIFF: StateDiff = Object.freeze({
  moved: [],
  facings: [],
  quantity: [],
  added: [],
  removed: [],
}) as StateDiff;

function bySku(products: ProductInventory[]): Map<string, ProductInventory> {
  return new Map(products.map((product) => [product.sku, product]));
}

/**
 * The changes from `prev` to `next`, read from state alone: actions only ever label them.
 * States of different stores are not comparable and give `EMPTY_DIFF`.
 */
export function diffStates(prev: StoreResponse, next: StoreResponse): StateDiff {
  if (prev.store_id !== next.store_id) return EMPTY_DIFF;
  const before = bySku(prev.products);
  const after = bySku(next.products);
  const diff: StateDiff = { moved: [], facings: [], quantity: [], added: [], removed: [] };

  for (const sku of [...new Set([...before.keys(), ...after.keys()])].sort()) {
    const from = before.get(sku);
    const to = after.get(sku);
    if (!from) {
      diff.added.push(sku);
      continue;
    }
    if (!to) {
      diff.removed.push(sku);
      continue;
    }
    if (from.shelf_id !== to.shelf_id || from.slot_id !== to.slot_id) {
      diff.moved.push({
        sku,
        from: { shelf_id: from.shelf_id, slot_id: from.slot_id },
        to: { shelf_id: to.shelf_id, slot_id: to.slot_id },
      });
    }
    if (from.facings !== to.facings) diff.facings.push({ sku, before: from.facings, after: to.facings });
    const shelfDelta = to.shelf_quantity - from.shelf_quantity;
    const backroomDelta = to.backroom_quantity - from.backroom_quantity;
    if (shelfDelta !== 0 || backroomDelta !== 0) diff.quantity.push({ sku, shelfDelta, backroomDelta });
  }
  return diff;
}

export function isEmptyDiff(diff: StateDiff): boolean {
  return (
    diff.moved.length === 0 &&
    diff.facings.length === 0 &&
    diff.quantity.length === 0 &&
    diff.added.length === 0 &&
    diff.removed.length === 0
  );
}

/** SKUs still in the next state that `diff` changes (moved, re-faced, restocked or added), sorted. */
export function changedSkus(diff: StateDiff): string[] {
  return [
    ...new Set([
      ...diff.moved.map((item) => item.sku),
      ...diff.facings.map((item) => item.sku),
      ...diff.quantity.map((item) => item.sku),
      ...diff.added,
    ]),
  ].sort();
}
