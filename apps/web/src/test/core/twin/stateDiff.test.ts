import { describe, expect, it } from "vitest";
import { diffStates, EMPTY_DIFF, isEmptyDiff } from "@/core/twin/stateDiff";
import { sampleStoreState } from "@/test/sampleState";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/** The sample state with one product changed, or removed with `null`. */
function withProduct(sku: string, change: Partial<ProductInventory> | null): StoreResponse {
  const state = sampleStoreState();
  const products = state.products.flatMap((product) =>
    product.sku !== sku ? [product] : change ? [{ ...product, ...change }] : [],
  );
  return { ...state, products };
}

describe("diffStates", () => {
  it("finds nothing between equal states", () => {
    const diff = diffStates(sampleStoreState(), sampleStoreState());
    expect(diff).toEqual(EMPTY_DIFF);
    expect(isEmptyDiff(diff)).toBe(true);
  });

  it("finds a move from one slot to another", () => {
    const diff = diffStates(sampleStoreState(), withProduct("P002", { shelf_id: "A02", slot_id: "A02-S02" }));
    expect(diff.moved).toEqual([
      { sku: "P002", from: { shelf_id: "A01", slot_id: "A01-S02" }, to: { shelf_id: "A02", slot_id: "A02-S02" } },
    ]);
    expect(diff.facings).toEqual([]);
    expect(diff.quantity).toEqual([]);
  });

  it("finds a move within the same shelf", () => {
    const diff = diffStates(sampleStoreState(), withProduct("P002", { slot_id: "A01-S05" }));
    expect(diff.moved).toEqual([
      { sku: "P002", from: { shelf_id: "A01", slot_id: "A01-S02" }, to: { shelf_id: "A01", slot_id: "A01-S05" } },
    ]);
  });

  it("finds a facings change", () => {
    const diff = diffStates(sampleStoreState(), withProduct("P002", { facings: 5 }));
    expect(diff.facings).toEqual([{ sku: "P002", before: 2, after: 5 }]);
    expect(diff.moved).toEqual([]);
  });

  it("finds shelf and backroom quantity changes as signed deltas", () => {
    const diff = diffStates(sampleStoreState(), withProduct("P002", { shelf_quantity: 15, backroom_quantity: 0 }));
    expect(diff.quantity).toEqual([{ sku: "P002", shelfDelta: 5, backroomDelta: -5 }]);
  });

  it("reports a one-sided quantity change with a zero delta on the other side", () => {
    const diff = diffStates(sampleStoreState(), withProduct("P002", { shelf_quantity: 7 }));
    expect(diff.quantity).toEqual([{ sku: "P002", shelfDelta: -3, backroomDelta: 0 }]);
  });

  it("finds added and removed SKUs", () => {
    const prev = withProduct("P003", null);
    const next = withProduct("P002", null);
    const diff = diffStates(prev, next);
    expect(diff.added).toEqual(["P003"]);
    expect(diff.removed).toEqual(["P002"]);
    expect(diff.moved).toEqual([]);
  });

  it("lists one product under every kind of change it has, and several products sorted by SKU", () => {
    const prev = sampleStoreState();
    const next = sampleStoreState();
    next.products = next.products.map((product) => {
      if (product.sku === "P003") return { ...product, shelf_quantity: 42, backroom_quantity: 48 };
      if (product.sku === "P001") return { ...product, slot_id: "A01-S03", facings: product.facings + 1 };
      return product;
    });
    const diff = diffStates(prev, next);
    expect(diff.moved.map((move) => move.sku)).toEqual(["P001"]);
    expect(diff.facings.map((change) => change.sku)).toEqual(["P001"]);
    expect(diff.quantity).toEqual([{ sku: "P003", shelfDelta: 12, backroomDelta: -12 }]);
  });

  it("ignores product order and version-only changes", () => {
    const prev = sampleStoreState();
    const next = sampleStoreState();
    next.context_version = `${next.store_id}:later`;
    next.products = next.products.map((product) => ({ ...product, version: product.version + 1 })).reverse();
    expect(isEmptyDiff(diffStates(prev, next))).toBe(true);
  });

  it("does not compare states of different stores", () => {
    const other = { ...withProduct("P002", { facings: 9 }), store_id: "other-store" };
    expect(diffStates(sampleStoreState(), other)).toBe(EMPTY_DIFF);
  });

  it("does not change either state", () => {
    const prev = sampleStoreState();
    const next = withProduct("P001", { facings: 9 });
    const before = structuredClone([prev, next]);
    diffStates(prev, next);
    expect([prev, next]).toEqual(before);
  });
});
