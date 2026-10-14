import { describe, expect, it } from "vitest";
import { demoStoreState } from "@/fixtures/demo/store";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { toSceneStore, storeLayout } from "@/scene/layout";
import { buildStock, unitsHeld } from "@/scene/entities/stock/Stock";
import { slotUnits } from "@/scene/entities/stock/placement";
import { surfacesOf } from "@/scene/entities/stock/surfaces";
import { stockState } from "@/core/twin/fixtureStock";
import { STOCK_STATE } from "@/enums/stock.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";

const FIRST_FILLER = 101;
const isFiller = (sku: string) => Number(sku.slice(1)) >= FIRST_FILLER;

describe("demo filler stock", () => {
  const state = demoStoreState();
  const scene = toSceneStore(state);
  const fillers = scene.store.products.filter((product) => isFiller(product.productId));

  it("fills most free slots, the same on every load, with no placement issues", () => {
    expect(fillers.length).toBeGreaterThan(400);
    expect(scene.issues).toEqual([]);
    expect(demoStoreState()).toEqual(state);
  });

  it("is never low or out of stock, so the demo's alerts stay the named products'", () => {
    expect(fillers.every((product) => stockState(product) === STOCK_STATE.Ok)).toBe(true);
  });

  it("holds no more than its facings draw", () => {
    const held = unitsHeld(scene.store);
    expect(fillers.every((product) => product.shelfQuantity <= (held.get(product.productId) ?? 0))).toBe(true);
  });

  it("leaves the simulation's move targets free", () => {
    expect(toSceneStore(demoSimulation(state).state).issues).toEqual([]);
  });
});

describe("slotUnits", () => {
  it("is what a full slot holds, drawn as fewer, bigger items, and one item for one unit", () => {
    const shelf = storeLayout.shelves[0];
    const holders = [
      { id: shelf.shelfId, kind: ENTITY_TYPE.Shelf, slots: shelf.slots },
      ...storeLayout.equipment.map((item) => ({ id: item.equipmentId, kind: item.kind, slots: item.slots })),
    ];
    let checked = 0;
    for (const holder of holders) {
      const slot = holder.slots[0];
      const surface = slot && surfacesOf(holder.kind)[slot.surface];
      if (!slot || !surface) continue;
      const product = { productId: "P900", shelfId: holder.id, slotId: slot.slotId, facings: 3, shelfQuantity: 10_000, backroomQuantity: 0, version: 1 };
      const drawn = (shelfQuantity: number) =>
        Object.values(buildStock({ ...storeLayout, products: [{ ...product, shelfQuantity }] })).flat().length;
      const full = slotUnits(surface, slot, 3);
      expect(unitsHeld({ ...storeLayout, products: [product] }).get("P900")).toBe(full);
      expect(drawn(10_000)).toBeGreaterThan(0);
      expect(drawn(10_000)).toBeLessThanOrEqual(full);
      expect(drawn(full)).toBe(drawn(10_000));
      expect(drawn(1)).toBe(1);
      expect(drawn(0)).toBe(0);
      checked += 1;
    }
    expect(checked).toBeGreaterThan(3);
  });
});
