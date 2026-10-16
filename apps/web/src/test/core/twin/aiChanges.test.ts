import { describe, expect, it } from "vitest";
import { aiChangeCount, aiChanges } from "@/core/twin/aiChanges";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import type { StoreResponse } from "@/types/twin.type";

const live = demoStoreState();
const product = (state: StoreResponse, sku: string) => state.products.find((item) => item.sku === sku)!;

/** `state` with `sku` changed by `patch`. */
function patched(state: StoreResponse, sku: string, patch: Partial<StoreResponse["products"][number]>): StoreResponse {
  return { ...state, products: state.products.map((item) => (item.sku === sku ? { ...item, ...patch } : item)) };
}

describe("aiChanges", () => {
  it("groups the demo proposal as Moved, Facings and Replenished, matching its diff", () => {
    const proposal = demoSimulation(live).state;
    const changes = aiChanges(live, proposal);
    expect(changes.moved).toEqual([
      { sku: "P005", from: "A03-S22", to: "B01-S22" },
      { sku: "P007", from: "B02-S20", to: "B02-S22" },
      { sku: "P008", from: "C01-S21", to: "A02-S22" },
    ]);
    expect(changes.facings).toEqual([{ sku: "P004", before: product(live, "P004").facings, after: 4 }]);
    expect(changes.replenished).toEqual([
      { sku: "P003", before: product(live, "P003").shelf_quantity, after: product(proposal, "P003").shelf_quantity },
    ]);
    expect(aiChangeCount(changes)).toBe(5);
  });

  it("reads before and after from the two states, never from the delta", () => {
    const after = patched(live, "P001", { shelf_quantity: 11 });
    const before = patched(live, "P001", { shelf_quantity: 3 });
    expect(aiChanges(before, after).replenished).toEqual([{ sku: "P001", before: 3, after: 11 }]);
  });

  it("lists a product in each group it changes in", () => {
    const after = patched(live, "P007", { slot_id: "B02-S22", facings: product(live, "P007").facings + 1 });
    const changes = aiChanges(live, after);
    expect(changes.moved.map((row) => row.sku)).toEqual(["P007"]);
    expect(changes.facings.map((row) => row.sku)).toEqual(["P007"]);
  });

  it("leaves out a shelf count that went down, and backroom-only changes", () => {
    const sold = patched(live, "P001", { shelf_quantity: product(live, "P001").shelf_quantity - 2 });
    const backroom = patched(live, "P002", { backroom_quantity: product(live, "P002").backroom_quantity + 5 });
    expect(aiChangeCount(aiChanges(live, sold))).toBe(0);
    expect(aiChangeCount(aiChanges(live, backroom))).toBe(0);
  });

  it("is empty for the same state, or states of different stores", () => {
    expect(aiChangeCount(aiChanges(live, live))).toBe(0);
    const other = { ...patched(live, "P007", { slot_id: "B02-S22" }), store_id: "store-002" };
    expect(aiChangeCount(aiChanges(live, other))).toBe(0);
  });
});
