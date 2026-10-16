import type { StoreResponse } from "@/types/twin.type";
import { diffStates } from "./stateDiff";

/** A product moved from one slot to another, as both states have it. */
export type MovedRow = { sku: string; from: string; to: string };
/** A product's facings, or its shelf count, before and after, as both states have them. */
export type CountRow = { sku: string; before: number; after: number };

/** What an AI change does to the store, grouped the way the AI CHANGES list shows it. Each group is sorted by SKU. */
export type AiChanges = {
  moved: MovedRow[];
  facings: CountRow[];
  /** Products whose shelf count went up. */
  replenished: CountRow[];
};

/**
 * The AI CHANGES of going from `before` to `after` (Live to a proposal, or Live before and
 * after an executed one), read from `stateDiff`. Every number is one of the two states'
 * own values: nothing is added up here. A shelf count that went down is not a replenishment
 * and is left out, as are products added or removed.
 */
export function aiChanges(before: StoreResponse, after: StoreResponse): AiChanges {
  const diff = diffStates(before, after);
  const was = new Map(before.products.map((product) => [product.sku, product]));
  const now = new Map(after.products.map((product) => [product.sku, product]));
  return {
    moved: diff.moved.map(({ sku, from, to }) => ({ sku, from: from.slot_id, to: to.slot_id })),
    facings: diff.facings.map(({ sku, before: from, after: to }) => ({ sku, before: from, after: to })),
    replenished: diff.quantity
      .filter((item) => item.shelfDelta > 0)
      .map(({ sku }) => ({ sku, before: was.get(sku)!.shelf_quantity, after: now.get(sku)!.shelf_quantity })),
  };
}

/** How many rows `changes` lists. */
export function aiChangeCount(changes: AiChanges): number {
  return changes.moved.length + changes.facings.length + changes.replenished.length;
}
