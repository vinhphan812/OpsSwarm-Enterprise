import type { PromotionsSummary } from "@/types/promotion.type";
import type { RevenueSummary, RevenueTotals } from "@/types/revenue.type";
import { BUCKET_SIZE, REVENUE_PERIOD, type RevenuePeriod } from "@/enums/commerce.enum";
import { STOCK_KIND } from "@/enums/scene.enum";

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** Bars per window: the hours of today, or the days of the last week or month. */
const BUCKETS: Record<RevenuePeriod, { count: number; ms: number }> = {
  [REVENUE_PERIOD.Today]: { count: 24, ms: HOUR_MS },
  [REVENUE_PERIOD.Week]: { count: 7, ms: DAY_MS },
  [REVENUE_PERIOD.Month]: { count: 30, ms: DAY_MS },
};

const ZERO_TOTALS: RevenueTotals = { revenue: 0, transactions: 0, average_basket: 0, margin_rate: 0 };

/**
 * A report with every figure at 0, in the shape the sales API returns. Shown while `GET /revenue` is in flight
 * or has failed: the buckets and categories are real, so the chart axis and legend already render.
 */
export function emptyRevenue(storeId: string, period: RevenuePeriod, now = new Date()): RevenueSummary {
  const { count, ms } = BUCKETS[period];
  // Today starts at midnight; a longer window ends with today.
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (period !== REVENUE_PERIOD.Today) start.setTime(start.getTime() - (count - 1) * ms);

  return {
    ...ZERO_TOTALS,
    store_id: storeId,
    period,
    start: start.toISOString(),
    end: new Date(now.getTime()).toISOString(),
    currency: "USD",
    lost_to_stockout: 0,
    previous: ZERO_TOTALS,
    bucket_size: period === REVENUE_PERIOD.Today ? BUCKET_SIZE.Hour : BUCKET_SIZE.Day,
    buckets: Array.from({ length: count }, (_, i) => ({
      start: new Date(start.getTime() + i * ms).toISOString(),
      revenue: 0,
    })),
    categories: Object.values(STOCK_KIND).map((category) => ({ category, revenue: 0 })),
    top_skus: [],
    slow_skus: [],
  };
}

/** No promotions, in the shape the promotions API returns. Shown while `GET /promotions` is in flight or has failed. */
export function emptyPromotions(storeId: string): PromotionsSummary {
  return { store_id: storeId, revenue: 0, incremental_revenue: 0, discount_cost: 0, promotions: [] };
}

