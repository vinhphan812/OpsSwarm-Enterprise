import { STOCK_KIND, type StockKind } from "@/enums/scene.enum";
import { STOCK_SHAPE, type StockShape } from "@/enums/stock.enum";
import type { Tuple3 } from "@/scene/utils/transform";


/**
 * A kind of item, as low-poly packaging. `size` is [width, height, depth] in meters;
 * for cylinders and spheres width and depth are the diameter.
 */
export type StockItem = {
  shape: StockShape;
  size: Tuple3;
  color: string;
  /** Same items stack on top of each other (cans, trays, boxes). */
  stacks?: boolean;
};

/**
 * Packaging drawn on each kind of surface. Twin state carries no product looks, so
 * every product on the same kind of surface looks the same.
 */
const STOCK_ITEM: Record<StockKind, StockItem> = {
  /** A cereal box on the gondolas. */
  [STOCK_KIND.Packaged]: { shape: STOCK_SHAPE.Box, size: [0.19, 0.25, 0.07], color: "#e8b33c" },
  /** Apples heaped in the produce trays and crates. */
  [STOCK_KIND.Fruit]: { shape: STOCK_SHAPE.Sphere, size: [0.075, 0.072, 0.075], color: "#c0392b" },
  /** Meat trays in the glass-door coolers. */
  [STOCK_KIND.Fresh]: { shape: STOCK_SHAPE.Box, size: [0.22, 0.04, 0.15], color: "#c0392b", stacks: true },
  /** Frozen boxes in the open chillers. */
  [STOCK_KIND.Frozen]: { shape: STOCK_SHAPE.Box, size: [0.18, 0.05, 0.14], color: "#90caf9", stacks: true },
};

export function stockItemFor(kind: StockKind): StockItem {
  return STOCK_ITEM[kind];
}
