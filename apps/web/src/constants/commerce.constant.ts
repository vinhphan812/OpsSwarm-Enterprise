import { STOCK_KIND, type StockKind } from "@/enums/scene.enum";

/**
 * Chart color of each category, fixed so a category keeps its color whatever the others do. Categorical slots
 * 1-4 of the dataviz palette, stepped for the dark panel (validated against --color-panel).
 */
export const CATEGORY_COLOR: Record<StockKind, string> = {
  [STOCK_KIND.Packaged]: "var(--color-series-1)",
  [STOCK_KIND.Fruit]: "var(--color-series-2)",
  [STOCK_KIND.Fresh]: "var(--color-series-3)",
  [STOCK_KIND.Frozen]: "var(--color-series-4)",
};

/** Color of a category the palette does not know. */
export const OTHER_CATEGORY_COLOR = "var(--color-ink-faint)";

/** Rows each SKU list shows. */
export const SKU_LIST_SIZE = 5;
