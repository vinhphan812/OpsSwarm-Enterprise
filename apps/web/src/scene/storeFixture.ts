import { MIDDLE_DECK_TOP } from "./dimensions";
import type { ShelfFixture, SlotFixture, StoreFixture } from "./types";

const SLOT_X = [-0.7, 0, 0.7] as const;

function slotsFor(shelfId: string): SlotFixture[] {
  return SLOT_X.map((x, index) => ({
    slotId: `${shelfId}-S0${index + 1}`,
    position: { x, y: MIDDLE_DECK_TOP, z: 0 },
  }));
}

function shelf(
  shelfId: string,
  x: number,
  z: number,
  color: string,
): ShelfFixture {
  return {
    shelfId,
    position: { x, y: 0, z },
    color,
    slots: slotsFor(shelfId),
  };
}

/**
 * View fixture for the scaffold scene.
 * Positions are not Live Twin truth. Issue #4 replaces this module with twin state.
 */
export const storeFixture: StoreFixture = {
  storeId: "store-001",
  shelves: [
    shelf("A01", -1.6, -1.6, "#8d6e63"),
    shelf("A02", 1.6, -1.6, "#8d6e63"),
    shelf("B01", -1.6, 1.6, "#6d8b74"),
    shelf("B02", 1.6, 1.6, "#6d8b74"),
  ],
  products: [
    {
      productId: "P001",
      sku: "P001",
      shelfId: "A01",
      slotId: "A01-S01",
      facings: 3,
      color: "#e85d4c",
    },
    {
      productId: "P002",
      sku: "P002",
      shelfId: "A02",
      slotId: "A02-S01",
      facings: 2,
      color: "#3d7ea6",
    },
  ],
};
