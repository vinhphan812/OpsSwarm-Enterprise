import { describe, expect, it } from "vitest";
import { patchProduct } from "@/core/api/sources/memorySource";
import { diffStates } from "@/core/twin/stateDiff";
import { inspectProduct, transferIssues, twinIssues } from "@/core/twin/twinIssues";
import { slotMarksOf } from "@/scene/entities/stock/SlotMarks";
import { unitsDrawn } from "@/scene/entities/stock/Stock";
import { toSceneStore } from "@/scene/layout";
import { sampleStoreState } from "@/test/sampleState";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/** P001: 3 facings, 8 on the shelf, 42 in the backroom. */
const before = sampleStoreState();
const withP001 = (patch: Partial<ProductInventory>): StoreResponse => patchProduct(sampleStoreState(), "P001", patch);
const issuesAfter = (patch: Partial<ProductInventory>) => transferIssues(diffStates(before, withP001(patch)));

describe("transferIssues", () => {
  it("accepts a matching backroom → shelf transfer", () => {
    expect(issuesAfter({ shelf_quantity: 12, backroom_quantity: 38 })).toEqual([]);
  });

  it("flags a one-sided restock, a backroom loss, and sides that do not match", () => {
    expect(issuesAfter({ shelf_quantity: 13 })).toEqual([
      { sku: "P001", code: "inconsistentTransfer", values: { shelf: "+5", backroom: "0" } },
    ]);
    expect(issuesAfter({ backroom_quantity: 30 })).toEqual([
      { sku: "P001", code: "inconsistentTransfer", values: { shelf: "0", backroom: "-12" } },
    ]);
    expect(issuesAfter({ shelf_quantity: 12, backroom_quantity: 40 })).toHaveLength(1);
  });

  it("leaves a sale and a delivery alone", () => {
    expect(issuesAfter({ shelf_quantity: 6 })).toEqual([]);
    expect(issuesAfter({ backroom_quantity: 60 })).toEqual([]);
    expect(transferIssues(null)).toEqual([]);
  });

  it("keeps a flagged product drawn and on its card", () => {
    const live = withP001({ shelf_quantity: 13 });
    const issues = twinIssues(live, [], diffStates(before, live));
    expect(issues.map((issue) => issue.code)).toEqual(["inconsistentTransfer"]);
    expect(inspectProduct("P001", live, issues)).toMatchObject({ kind: "ok", transfer: issues[0] });
    expect(inspectProduct("P002", live, issues)).not.toHaveProperty("transfer");
  });
});

describe("units not shown", () => {
  it("draws shelf units only up to what the facings hold", () => {
    const holds = unitsDrawn(toSceneStore(withP001({ shelf_quantity: 10_000 })).store).get("P001")!;
    expect(holds).toBeGreaterThan(8);
    expect(unitsDrawn(toSceneStore(withP001({ shelf_quantity: holds + 7 })).store).get("P001")).toBe(holds);
    expect(unitsDrawn(toSceneStore(before).store).get("P001")).toBe(8);
  });
});

describe("restock glow", () => {
  it("glows the slot of a recent shelf gain while the state still has it", () => {
    const after = withP001({ shelf_quantity: 12, backroom_quantity: 38 });
    const change = { diff: diffStates(before, after), at: Date.now(), before };
    expect(slotMarksOf(toSceneStore(after).store, change).changed.map((box) => box.slotId)).toEqual(["A01-S01"]);
    // A later state with another shelf count is not what the change set.
    expect(slotMarksOf(toSceneStore(withP001({ shelf_quantity: 11 })).store, change).changed).toEqual([]);
  });

  it("does not glow a sale", () => {
    const after = withP001({ shelf_quantity: 6 });
    const change = { diff: diffStates(before, after), at: Date.now(), before };
    expect(slotMarksOf(toSceneStore(after).store, change).changed).toEqual([]);
  });
});
