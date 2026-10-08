export type { EquipmentKind } from "@/enums/scene.enum";
import type { EquipmentKind, StockKind } from "@/enums/scene.enum";

export type Vec3 = {
  x: number;
  y: number;
  z: number;
};

export type SlotFixture = {
  slotId: string;
  /** Center of the slot's front edge on its surface, in the fixture's local frame. */
  position: Vec3;
  /** Index into the fixture's display surfaces. */
  surface: number;
  /** Slot center along the surface width, in the surface's own frame. */
  offset: number;
  width: number;
};

export type ShelfFixture = {
  shelfId: string;
  position: Vec3;
  /** Radians about Y. At 0 the shelf front faces +Z. */
  rotationY: number;
  /** Merchandise group shown in the hover label. */
  category: StockKind;
  color: string;
  slots: SlotFixture[];
};

export type ProductFixture = {
  /** Entity id: the product's SKU in the API. */
  productId: string;
  shelfId: string;
  slotId: string;
  facings: number;
  /** Units on the shelf; the scene draws one item per unit, front row first. */
  shelfQuantity: number;
  backroomQuantity: number;
  /** Product record version in the API. */
  version: number;
};

/** Non-shelf store furniture. Position is the center of the footprint on the floor. */
export type EquipmentFixture = {
  equipmentId: string;
  kind: EquipmentKind;
  position: Vec3;
  /** Radians about Y. At 0 the front faces +Z. */
  rotationY: number;
  /** Display slots; empty for checkouts, barriers, and backstock crates. */
  slots: SlotFixture[];
};

export type StoreFixture = {
  storeId: string;
  shelves: ShelfFixture[];
  products: ProductFixture[];
  equipment: EquipmentFixture[];
};
