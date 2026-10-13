import type { FixtureKind } from "@/enums/scene.enum";
import { STOCK_SHAPE } from "@/enums/stock.enum";
import type { SlotFixture } from "@/types/scene.type";
import { stockItemFor, type StockItem } from "./catalog";
import { surfacesOf } from "./surfaces";

/** Gap between two facings of packaged goods, in meters. */
export const FACING_GAP = 0.008;

/** Keeps a slot that fits a whole number of items exactly from losing one to rounding. */
const EPSILON = 1e-9;

/**
 * The most facings of `item` that fit side by side across `slot` at the item's natural
 * width. Packaged goods keep `FACING_GAP` between facings; fruit lies ball to ball. The
 * layout is the FE's capacity source; a `max_facings` from the API will override it (#92).
 */
export function slotCapacity(slot: SlotFixture, item: StockItem): number {
  const [w] = item.size;
  if (item.shape === STOCK_SHAPE.Sphere) return Math.floor(slot.width / w + EPSILON);
  return Math.floor((slot.width + FACING_GAP) / (w + FACING_GAP) + EPSILON);
}

/** `slotCapacity` of a slot on a fixture of `kind`, for the item that fixture shows; 0 for a slot it has no surface for. */
export function capacityOf(kind: FixtureKind, slot: SlotFixture): number {
  const surface = surfacesOf(kind)[slot.surface];
  return surface ? slotCapacity(slot, stockItemFor(surface.kind)) : 0;
}
