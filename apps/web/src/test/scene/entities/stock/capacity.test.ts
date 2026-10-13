import { Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { patchProduct } from "@/core/api/sources/memorySource";
import { diffStates } from "@/core/twin/stateDiff";
import { inspectProduct, twinIssues } from "@/core/twin/twinIssues";
import { ENTITY_TYPE, EQUIPMENT_KIND, STOCK_KIND } from "@/enums/scene.enum";
import { capacityOf, slotCapacity } from "@/scene/entities/stock/capacity";
import { stockItemFor } from "@/scene/entities/stock/catalog";
import { slotMarksOf } from "@/scene/entities/stock/SlotMarks";
import { buildStock } from "@/scene/entities/stock/Stock";
import { storeLayout, toSceneStore } from "@/scene/layout";
import { sampleStoreState } from "@/test/sampleState";
import type { FixtureKind } from "@/enums/scene.enum";
import type { StoreResponse } from "@/types/twin.type";

/** The first slot of a fixture of `kind` in the layout. */
function firstSlot(kind: FixtureKind) {
  const holder =
    kind === ENTITY_TYPE.Shelf ? storeLayout.shelves[0] : storeLayout.equipment.find((item) => item.kind === kind);
  return holder!.slots[0]!;
}

const withP001 = (facings: number): StoreResponse => patchProduct(sampleStoreState(), "P001", { facings });

describe("slotCapacity", () => {
  it("fits each kind of item at its natural width", () => {
    expect(capacityOf(ENTITY_TYPE.Shelf, firstSlot(ENTITY_TYPE.Shelf))).toBe(5);
    expect(capacityOf(EQUIPMENT_KIND.GlassDoorCooler, firstSlot(EQUIPMENT_KIND.GlassDoorCooler))).toBe(2);
    expect(capacityOf(EQUIPMENT_KIND.OpenChiller, firstSlot(EQUIPMENT_KIND.OpenChiller))).toBe(3);
    expect(capacityOf(EQUIPMENT_KIND.ProduceRack, firstSlot(EQUIPMENT_KIND.ProduceRack))).toBe(7);
  });

  it("keeps a gap between boxes but not between fruit", () => {
    const slot = { ...firstSlot(ENTITY_TYPE.Shelf), width: 0.3 };
    const box = { ...stockItemFor(STOCK_KIND.Packaged), size: [0.1, 0.2, 0.1] as const };
    const fruit = { ...stockItemFor(STOCK_KIND.Fruit), size: [0.1, 0.1, 0.1] as const };
    // Three boxes need two gaps more than 0.3 m; three apples fit exactly.
    expect(slotCapacity(slot, { ...box, size: [...box.size] })).toBe(2);
    expect(slotCapacity(slot, { ...fruit, size: [...fruit.size] })).toBe(3);
  });
});

describe("facings over capacity", () => {
  it("accepts facings up to the slot's capacity", () => {
    expect(toSceneStore(withP001(5)).issues).toEqual([]);
  });

  it("draws an overflow capped at the capacity and reports it", () => {
    const { store, issues } = toSceneStore(withP001(12));
    expect(issues).toEqual([
      { sku: "P001", code: "facingsOverCapacity", values: { facings: 12, capacity: 5, slotId: "A01-S01" } },
    ]);
    // Still drawn, never as many columns as the state asks for.
    expect(store.products.find((product) => product.productId === "P001")?.facings).toBe(12);
    const drawn = (state: StoreResponse) => {
      const scene = toSceneStore(state).store;
      const products = scene.products.map((product) =>
        product.productId === "P001" ? { ...product, shelfQuantity: 10_000 } : product,
      );
      return buildStock({ ...scene, products: products.filter((product) => product.productId === "P001") }).box;
    };
    expect(drawn(withP001(12))).toHaveLength(drawn(withP001(5)).length);
  });

  it("keeps every drawn item inside its slot", () => {
    const store = toSceneStore(withP001(12)).store;
    const p001 = { ...store.products.find((product) => product.productId === "P001")!, shelfQuantity: 10_000 };
    const items = buildStock({ ...store, products: [p001] }).box;
    // The overflow mark is the slot as a unit cube: inside it, the slot runs from -0.5 to 0.5.
    const toSlot = slotMarksOf(store, null).overflow[0]!.matrix.clone().invert();
    for (const item of items) {
      const { x } = new Vector3().setFromMatrixPosition(item.matrix).applyMatrix4(toSlot);
      expect(Math.abs(x)).toBeLessThan(0.5);
    }
  });

  it("lists the overflow without hiding the product from its card", () => {
    const live = withP001(12);
    const issues = twinIssues(live, []);
    expect(issues.map((issue) => issue.code)).toEqual(["facingsOverCapacity"]);
    const inspection = inspectProduct("P001", live, issues);
    expect(inspection).toMatchObject({ kind: "ok", overflow: issues[0] });
    expect(inspectProduct("P002", live, issues)).not.toHaveProperty("overflow");
  });
});

describe("slotMarksOf", () => {
  it("outlines only overflowing slots", () => {
    expect(slotMarksOf(toSceneStore(withP001(5)).store, null).overflow).toEqual([]);
    const { overflow } = slotMarksOf(toSceneStore(withP001(12)).store, null);
    expect(overflow.map((box) => box.slotId)).toEqual(["A01-S01"]);
    // The box spans the slot's width.
    expect(new Vector3().setFromMatrixScale(overflow[0]!.matrix).x).toBeCloseTo(firstSlot(ENTITY_TYPE.Shelf).width);
  });

  it("glows the slot of a recent facings change while the state still has it", () => {
    const before = withP001(3);
    const after = withP001(5);
    const change = { diff: diffStates(before, after), at: Date.now(), before };
    expect(slotMarksOf(toSceneStore(after).store, change).changed.map((box) => box.slotId)).toEqual(["A01-S01"]);
    // A later state with other facings is not what the change set, so it is not cued.
    expect(slotMarksOf(toSceneStore(withP001(4)).store, change).changed).toEqual([]);
    expect(slotMarksOf(toSceneStore(after).store, null).changed).toEqual([]);
  });
});
