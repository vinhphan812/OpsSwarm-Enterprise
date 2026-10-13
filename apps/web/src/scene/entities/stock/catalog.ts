import { STOCK_KIND, type StockKind } from "@/enums/scene.enum";
import { STOCK_SHAPE, type StockShape } from "@/enums/stock.enum";
import type { Tuple3 } from "@/types/scene.type";


/**
 * A kind of item, as low-poly packaging. `size` is [width, height, depth] in meters;
 * for cylinders and spheres width and depth are the diameter.
 */
export type StockItem = {
  shape: StockShape;
  size: Tuple3;
  color: string;
  /** Packaging colors; each product takes one by its id, so neighbouring products read apart. */
  palette: readonly string[];
  /** Products vary their height down to this share of `size`, so a shelf does not read as one block. */
  minHeight: number;
  /** Same items stack on top of each other (cans, trays, boxes). */
  stacks?: boolean;
};

/**
 * Packaging drawn on each kind of surface. Twin state carries no product looks, so a
 * product's color and height are picked from its id: stable across reloads, but not data.
 */
const STOCK_ITEM: Record<StockKind, StockItem> = {
  /** A slim carton on the gondolas, five facings to a slot. */
  [STOCK_KIND.Packaged]: {
    shape: STOCK_SHAPE.Box,
    size: [0.065, 0.25, 0.07],
    color: "#e8b33c",
    palette: ["#e8b33c", "#d9534f", "#3f7cc4", "#4e9a5b", "#f08a3c", "#8e5bb5", "#f2e2c4", "#2f9c9c", "#c8443f", "#f5c542"],
    minHeight: 0.78,
  },
  /** Apples heaped in the produce trays. */
  [STOCK_KIND.Fruit]: {
    shape: STOCK_SHAPE.Sphere,
    size: [0.075, 0.072, 0.075],
    color: "#c0392b",
    palette: ["#c0392b", "#7cb342", "#f4c430", "#ef7d1a", "#a8323e", "#9ccc65"],
    minHeight: 1,
  },
  /** Meat trays in the glass-door coolers. */
  [STOCK_KIND.Fresh]: {
    shape: STOCK_SHAPE.Box,
    size: [0.22, 0.04, 0.15],
    color: "#c0392b",
    palette: ["#c0392b", "#e57373", "#f2d0c4", "#d98c5f", "#b5523b"],
    minHeight: 1,
    stacks: true,
  },
  /** Frozen boxes in the open chillers. */
  [STOCK_KIND.Frozen]: {
    shape: STOCK_SHAPE.Box,
    size: [0.18, 0.05, 0.14],
    color: "#90caf9",
    palette: ["#90caf9", "#e3f2fd", "#1e5aa8", "#4fc3f7", "#ffffff", "#5c6bc0"],
    minHeight: 1,
    stacks: true,
  },
};

export function stockItemFor(kind: StockKind): StockItem {
  return STOCK_ITEM[kind];
}

/**
 * A stable 0..1 number from a product id, for picking its looks: FNV-1a, then the
 * MurmurHash3 finalizer, so ids that differ in one digit (P001, P002) still land apart.
 */
export function idFraction(id: string, salt = 0): number {
  let hash = 2166136261 ^ salt;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x85ebca6b);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 0xc2b2ae35);
  hash ^= hash >>> 16;
  return (hash >>> 0) / 4294967296;
}

/** How a product's packaging looks: its color and its height as a share of the item's. */
export function productLook(item: StockItem, productId: string): { color: string; height: number } {
  const color = item.palette[Math.floor(idFraction(productId) * item.palette.length)] ?? item.color;
  const height = item.minHeight + (1 - item.minHeight) * idFraction(productId, 1);
  return { color, height };
}
