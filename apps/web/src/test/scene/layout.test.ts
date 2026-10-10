import { describe, expect, it } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { patchProduct } from "@/core/api/sources/memorySource";
import { sceneOf, toSceneStore } from "@/scene/layout";

/** A slot of A01 that no sample product occupies. */
const FREE_SLOT = "A01-S37";

describe("toSceneStore", () => {
  it("places every product of the sample", () => {
    const { store, issues } = toSceneStore(sampleStoreState());
    expect(issues).toEqual([]);
    expect(store.products).toHaveLength(sampleStoreState().products.length);
  });

  it("takes slot, facings, and stock from twin state", () => {
    const base = sampleStoreState();
    const original = base.products.find((product) => product.sku === "P001")!;
    const before = toSceneStore(base).store.products.find((product) => product.productId === "P001");
    expect(before).toMatchObject({
      shelfId: original.shelf_id,
      slotId: original.slot_id,
      facings: original.facings,
      shelfQuantity: original.shelf_quantity,
      backroomQuantity: original.backroom_quantity,
    });

    const changed = patchProduct(base, "P001", { facings: 5, slot_id: FREE_SLOT, shelf_quantity: 2 });
    const { store, issues } = toSceneStore(changed);
    const after = store.products.find((product) => product.productId === "P001");

    expect(issues).toEqual([]);
    expect(after).toMatchObject({ shelfId: original.shelf_id, slotId: FREE_SLOT, facings: 5, shelfQuantity: 2 });
    expect(store.products.find((product) => product.productId === "P002")).toEqual(
      toSceneStore(base).store.products.find((product) => product.productId === "P002"),
    );
    expect(store.shelves).toEqual(toSceneStore(base).store.shelves);
  });

  it("leaves out and reports a product the layout cannot place", () => {
    const placed = (patch: Parameters<typeof patchProduct>[2]) => {
      const { store, issues } = toSceneStore(patchProduct(sampleStoreState(), "P001", patch));
      expect(store.products.some((product) => product.productId === "P001")).toBe(false);
      return issues;
    };

    expect(placed({ shelf_id: "Z99", slot_id: "Z99-S01" })).toEqual([
      { sku: "P001", code: "unknownShelf", values: { shelfId: "Z99" } },
    ]);
    expect(placed({ slot_id: "A01-S99" })).toEqual([
      { sku: "P001", code: "slotNotOnShelf", values: { slotId: "A01-S99", shelfId: "A01" } },
    ]);
    expect(placed({ slot_id: "A02-S01" })).toEqual([
      { sku: "P001", code: "slotNotOnShelf", values: { slotId: "A02-S01", shelfId: "A01" } },
    ]);
    // Equipment without slots, such as a checkout, holds no products.
    expect(placed({ shelf_id: "CK01", slot_id: "CK01-S01" })[0]).toMatchObject({ code: "unknownShelf", values: { shelfId: "CK01" } });
  });

  it("keeps the first product in a slot and reports the one that collides", () => {
    const state = patchProduct(sampleStoreState(), "P002", { slot_id: "A01-S01" });
    const { store, issues } = toSceneStore(state);
    expect(store.products.find((product) => product.slotId === "A01-S01")?.productId).toBe("P001");
    expect(issues).toEqual([{ sku: "P002", code: "slotTaken", values: { slotId: "A01-S01", owner: "P001" } }]);
  });

  it("computes each state once", () => {
    const state = sampleStoreState();
    expect(sceneOf(state)).toBe(sceneOf(state));
  });
});

describe("crates", () => {
  it("are decor, not shelves: no slots, and a product put on one is left out", () => {
    const crates = toSceneStore(sampleStoreState()).store.equipment.filter((item) => item.kind.startsWith("crate-"));
    expect(crates.length).toBeGreaterThan(0);
    for (const crate of crates) expect(crate.slots, crate.equipmentId).toEqual([]);

    const onCrate = patchProduct(sampleStoreState(), "P001", { shelf_id: "CW01", slot_id: "CW01-S01" });
    expect(toSceneStore(onCrate).issues).toEqual([{ sku: "P001", code: "unknownShelf", values: { shelfId: "CW01" } }]);
  });
});
