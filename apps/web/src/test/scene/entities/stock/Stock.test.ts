import { Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { toSceneStore } from "@/scene/layout";
import { buildStock } from "@/scene/entities/stock/Stock";
import { productLook, stockItemFor } from "@/scene/entities/stock/catalog";
import { STOCK_KIND } from "@/enums/scene.enum";

function positions(batches: ReturnType<typeof buildStock>) {
  return Object.values(batches)
    .flat()
    .map((item) => new Vector3().setFromMatrixPosition(item.matrix));
}

/** The store layout with the sample products on it. */
const storeFixture = toSceneStore(sampleStoreState()).store;

describe("buildStock", () => {
  it("is the same on every build", () => {
    const a = positions(buildStock(storeFixture)).map((p) => p.toArray());
    const b = positions(buildStock(storeFixture)).map((p) => p.toArray());
    expect(a.length).toBeGreaterThan(0);
    expect(a).toEqual(b);
  });

  it("draws packaged goods as boxes and fruit as a heap of spheres", () => {
    const batches = buildStock(storeFixture);
    const units = (id: string) => storeFixture.products.find((p) => p.productId === id)!.shelfQuantity;
    expect(batches.box).toHaveLength(units("P001") + units("P002"));
    expect(batches.sphere).toHaveLength(units("P003"));
    expect(batches.cylinder).toHaveLength(0);
  });

  describe("one product", () => {
    const product = storeFixture.products.find((p) => p.productId === "P001")!;
    const drawn = (change: Partial<typeof product>) =>
      positions(buildStock({ ...storeFixture, products: [{ ...product, ...change }] }));
    /** Enough stock to fill any slot, so the facings alone decide the count. */
    const FULL = 10_000;

    it("draws its facings at its slot, following twin changes", () => {
      const capacity = (facings: number) => drawn({ facings, shelfQuantity: FULL }).length;
      expect(capacity(1)).toBeGreaterThan(0);
      // Each extra facing adds the same column of items.
      expect(capacity(2)).toBe(2 * capacity(1));
      // A product moved to a slot that does not exist is not drawn.
      expect(drawn({ slotId: "A01-S99", shelfQuantity: FULL })).toHaveLength(0);
    });

    it("draws one item per unit of shelf stock, up to what the facings hold", () => {
      const capacity = drawn({ facings: 3, shelfQuantity: FULL }).length;
      expect(drawn({ facings: 3, shelfQuantity: 5 })).toHaveLength(5);
      expect(drawn({ facings: 3, shelfQuantity: capacity + 50 })).toHaveLength(capacity);
      expect(drawn({ facings: 3, shelfQuantity: 0 })).toHaveLength(0);
      expect(drawn({ facings: 0, shelfQuantity: 8 })).toHaveLength(0);
    });

    it("fills the front row first", () => {
      // P001 sits on a shelf turned to face +Z, so the front row has the largest z.
      const front = Math.max(...drawn({ facings: 3, shelfQuantity: FULL }).map((p) => p.z));
      const short = drawn({ facings: 3, shelfQuantity: 3 });
      for (const p of short) expect(p.z).toBeCloseTo(front);
    });
  });

  it("puts every product on its own shelf or equipment", () => {
    const holders = new Set([
      ...storeFixture.shelves.map((shelf) => shelf.shelfId),
      ...storeFixture.equipment.map((item) => item.equipmentId),
    ]);
    const slots = new Set([
      ...storeFixture.shelves.flatMap((shelf) => shelf.slots.map((slot) => slot.slotId)),
      ...storeFixture.equipment.flatMap((item) => item.slots.map((slot) => slot.slotId)),
    ]);
    for (const product of storeFixture.products) {
      expect(holders.has(product.shelfId), product.productId).toBe(true);
      expect(slots.has(product.slotId), product.productId).toBe(true);
      expect(product.slotId.startsWith(`${product.shelfId}-S`)).toBe(true);
    }
    expect(new Set(storeFixture.products.map((p) => p.slotId)).size).toBe(storeFixture.products.length);
  });
});

describe("productLook", () => {
  const item = stockItemFor(STOCK_KIND.Packaged);
  const ids = Array.from({ length: 50 }, (_, i) => `P${String(i + 1).padStart(3, "0")}`);

  it("is stable per product, from the item's palette, and never taller than the item", () => {
    for (const id of ids) {
      const look = productLook(item, id);
      expect(productLook(item, id)).toEqual(look);
      expect(item.palette).toContain(look.color);
      expect(look.height).toBeGreaterThanOrEqual(item.minHeight);
      expect(look.height).toBeLessThanOrEqual(1);
    }
  });

  it("spreads products over the palette, so neighbours read apart", () => {
    const colors = new Set(ids.map((id) => productLook(item, id).color));
    expect(colors.size).toBeGreaterThanOrEqual(item.palette.length - 2);
  });
});
