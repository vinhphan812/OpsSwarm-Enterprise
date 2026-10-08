import type { EquipmentKind, StockKind } from "@/enums/scene.enum";

export type Tuple3 = [number, number, number];

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

/**
 * A flat area that stock stands on, in the fixture's local frame. Items are laid
 * out across `width` (X) and back from the front edge over `depth` (Z), so the
 * surface front faces +Z after `rotationY`. `tilt` lowers the front edge.
 */
export type StockSurface = {
  kind: StockKind;
  /** Center of the top face. */
  center: Tuple3;
  width: number;
  depth: number;
  /** Clear height above the surface. */
  maxHeight: number;
  rotationY?: number;
  tilt?: number;
  /** Slots the surface is split into, side by side across its width. */
  slots: number;
};
