import { STOCK_KIND } from "@/enums/scene.enum";
import { STOCK_SHAPE } from "@/enums/stock.enum";
import type { SlotFixture, StockSurface, Tuple3 } from "@/types/scene.type";
import { FACING_GAP, slotCapacity } from "./capacity";
import { stockItemFor, type StockItem } from "./catalog";

/**
 * Where the items of one slot go, in the surface's own frame. Pure, so `Stock` draws
 * with it and demo data can size a full slot with it (`slotUnits`).
 */

const ROW_GAP = 0.005;

/** Takes an item position in the surface's own frame. */
export type Emit = (position: Tuple3) => void;

/**
 * The item at its natural width, no taller than the surface's clear height. Fruit
 * shrinks evenly so it stays round. Facings past the slot's capacity are not drawn
 * (`slotCapacity`), so items never run past the slot's edges.
 */
export function fitItem(item: StockItem, surface: StockSurface): StockItem {
  const [w, h, d] = item.size;
  if (item.shape === STOCK_SHAPE.Sphere) {
    const scale = Math.min(1, surface.maxHeight / h);
    return { ...item, size: [w * scale, h * scale, d * scale] };
  }
  return { ...item, size: [w, Math.min(h, surface.maxHeight), d] };
}

/**
 * Packaged goods: the facings side by side, rows behind them, stacked when the item
 * stacks. Emitted front row first, so a short stock empties the shelf from the back.
 */
export function layFacings(
  surface: StockSurface,
  slot: SlotFixture,
  item: StockItem,
  facings: number,
  emit: Emit,
) {
  const [w, h, d] = item.size;
  const total = facings * (w + FACING_GAP) - FACING_GAP;
  const rows = Math.max(1, Math.floor(surface.depth / (d + ROW_GAP)));
  const layers = item.stacks
    ? Math.max(1, Math.min(3, Math.floor(surface.maxHeight / h)))
    : 1;
  for (let row = 0; row < rows; row += 1) {
    const z = surface.depth / 2 - d / 2 - row * (d + ROW_GAP);
    for (let layer = 0; layer < layers; layer += 1) {
      for (let f = 0; f < facings; f += 1) {
        const x = slot.offset - total / 2 + w / 2 + f * (w + FACING_GAP);
        emit([x, layer * h + h / 2, z]);
      }
    }
  }
}

/**
 * Loose fruit: `facings` columns across the slot, a full bottom layer and a smaller
 * heap on top. Emitted bottom layer first, so a short stock loses the heap first.
 */
export function layHeap(
  surface: StockSurface,
  slot: SlotFixture,
  item: StockItem,
  facings: number,
  emit: Emit,
  maxLayers = 3,
) {
  const [w, h, d] = item.size;
  const back = Math.max(1, Math.floor(surface.depth / d));
  const layers = Math.max(
    1,
    Math.min(maxLayers, Math.floor(surface.maxHeight / (h * 0.85))),
  );
  const left = slot.offset - (facings * w) / 2;
  for (let layer = 0; layer < layers; layer += 1) {
    // Each layer sits in the hollows of the one below and shrinks toward the middle.
    for (let i = layer; i < facings - layer; i += 1) {
      for (let j = layer; j < back - layer; j += 1) {
        const x = left + (i + 0.5 + layer * 0.5) * w;
        const z = -surface.depth / 2 + (j + 0.5 + layer * 0.5) * d;
        if (Math.abs(z) > surface.depth / 2 - d / 2) continue;
        emit([x, h / 2 + layer * h * 0.8, z]);
      }
    }
  }
}

/** Lays `facings` of `item` on `surface` at `slot`: a heap of up to `maxLayers` for fruit, rows of facings for the rest. */
export function layItems(surface: StockSurface, slot: SlotFixture, item: StockItem, facings: number, emit: Emit, maxLayers?: number) {
  if (surface.kind === STOCK_KIND.Fruit) layHeap(surface, slot, item, facings, emit, maxLayers);
  else layFacings(surface, slot, item, facings, emit);
}

/** How many items `facings` of a slot hold when full: the most shelf stock `Stock` draws there. */
export function slotUnits(surface: StockSurface, slot: SlotFixture, facings: number): number {
  const natural = stockItemFor(surface.kind);
  const item = fitItem(natural, surface);
  let units = 0;
  layItems(surface, slot, item, Math.min(Math.max(0, facings), slotCapacity(slot, natural)), () => {
    units += 1;
  });
  return units;
}
