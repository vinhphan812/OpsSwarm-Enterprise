import { useMemo } from "react";
import { isDemoMode } from "@/core/twin/demoMode";
import { demoStockoutRisk } from "@/fixtures/demo/stockoutRisk";
import type { StockoutRisk } from "@/types/stockoutRisk.type";

/**
 * Stockout risk per product, or null while none is served. TODO(BE): apps/api serves no
 * stockout risk yet (`StockoutRisk`); on Live the overlay says so and colours nothing.
 * `?twin=demo` shows demo figures.
 */
export function useStockoutRisk(): StockoutRisk[] | null {
  return useMemo(() => (isDemoMode() ? demoStockoutRisk() : null), []);
}
