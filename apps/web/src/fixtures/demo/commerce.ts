import { defaultClient } from "@/core/api/client";
import { mulberry32 } from "@/core/utils/random";
import { BUCKET_SIZE, PROMOTION_KIND, PROMOTION_STATUS, REVENUE_PERIOD, type RevenuePeriod } from "@/enums/commerce.enum";
import { ENTITY_TYPE, type FixtureKind } from "@/enums/scene.enum";
import { surfacesOf } from "@/scene/entities/stock/surfaces";
import { storeLayout } from "@/scene/layout";
import type { RetailTwinClient } from "@/types/api.type";
import type { Promotion, PromotionsSummary } from "@/types/promotion.type";
import type { RevenueSummary, RevenueTotals, SkuRevenue } from "@/types/revenue.type";
import { DEMO_PRICES, demoCheckout, demoTransactions } from "./checkouts";
import { demoStoreState } from "./store";
import { demoAnomalies } from "./anomalies";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * `GET /revenue` and `GET /promotions` for the demo store. Today's revenue adds up the
 * demo checkouts' sales; earlier days are made up around it, the same on every load.
 */

const STORE_ID = "store-001";
const LANES = ["CK01", "CK02", "CK03"];
/** The demo's business day, matching the checkout sales. Local midnight starts it. */
const TODAY = new Date(2026, 9, 9);
const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const MARGIN_RATE = 0.27;
/** Units a day an out-of-stock product would have sold, for the lost-sales estimate. */
const LOST_UNITS_PER_DAY = 12;

/** What shoppers see on the shelf label; the twin has no product names. */
export const DEMO_NAMES: Readonly<Record<string, string>> = {
  P001: "Corn flakes 500 g",
  P002: "Oat crackers 250 g",
  P003: "Peanut butter 340 g",
  P004: "Penne pasta 500 g",
  P005: "Olive oil 500 ml",
  P006: "Instant coffee 200 g",
  P007: "Tomato sauce 400 g",
  P008: "Muesli 1 kg",
  P009: "Chicken breast 500 g",
  P010: "Frozen peas 1 kg",
  P011: "Gala apples",
  P012: "Bananas",
  P013: "Pork ribs 500 g",
  P014: "Pork sausages 400 g",
  P015: "Whole trout",
  P016: "Vanilla ice cream 1 L",
  P018: "Orange ice lolly",
  P020: "Frozen fries 1 kg",
};

const cents = (value: number) => Math.round(value * 100) / 100;

/** Merchandise group of a SKU: the stock kind of the fixture the demo store puts it on. */
function categoryOf(sku: string): string {
  const shelfId = demoStoreState().products.find((product) => product.sku === sku)?.shelf_id;
  const shelf = storeLayout.shelves.find((item) => item.shelfId === shelfId);
  const equipment = storeLayout.equipment.find((item) => item.equipmentId === shelfId);
  const kind: FixtureKind | undefined = shelf ? ENTITY_TYPE.Shelf : equipment?.kind;
  return (kind && surfacesOf(kind)[0]?.kind) ?? "packaged";
}

/** Today's sales of every lane. */
const SALES = LANES.flatMap((lane) => demoTransactions(lane));

/** Today's revenue and units per SKU, from the receipts. */
const TODAY_BY_SKU = (() => {
  const bySku = new Map<string, { revenue: number; units: number }>();
  for (const sku of Object.keys(DEMO_PRICES)) bySku.set(sku, { revenue: 0, units: 0 });
  for (const sale of SALES) {
    for (const line of sale.lines) {
      const entry = bySku.get(line.sku)!;
      entry.revenue += line.line_total;
      entry.units += line.quantity;
    }
  }
  return bySku;
})();

const TODAY_REVENUE = cents(LANES.reduce((sum, lane) => sum + (demoCheckout(lane)?.revenue_today ?? 0), 0));
const TODAY_TRANSACTIONS = SALES.length;

/**
 * Revenue and transactions of the last 60 days, today last. Earlier days vary around
 * today, busier at the weekend.
 */
const DAYS = (() => {
  const random = mulberry32(20261009);
  const basket = TODAY_REVENUE / TODAY_TRANSACTIONS;
  return Array.from({ length: 60 }, (_, index) => {
    const back = 59 - index;
    const date = new Date(TODAY.getTime() - back * DAY_MS);
    if (back === 0) return { date, revenue: TODAY_REVENUE, transactions: TODAY_TRANSACTIONS };
    const weekend = date.getDay() === 0 || date.getDay() === 6 ? 1.18 : 1;
    // A slow upward trend, so each window beats the one before it a little.
    const trend = 1 - back * 0.002;
    const revenue = cents(TODAY_REVENUE * (0.85 + random() * 0.3) * weekend * trend);
    return { date, revenue, transactions: Math.max(1, Math.round((revenue / basket) * (0.95 + random() * 0.1))) };
  });
})();

function totals(days: typeof DAYS, margin: number): RevenueTotals {
  const revenue = cents(days.reduce((sum, day) => sum + day.revenue, 0));
  const transactions = days.reduce((sum, day) => sum + day.transactions, 0);
  return { revenue, transactions, average_basket: transactions ? cents(revenue / transactions) : 0, margin_rate: margin };
}

const WINDOW_DAYS: Record<RevenuePeriod, number> = {
  [REVENUE_PERIOD.Today]: 1,
  [REVENUE_PERIOD.Week]: 7,
  [REVENUE_PERIOD.Month]: 30,
};

/** `GET /revenue?period=` for the demo store. */
export function demoRevenue(period: RevenuePeriod): RevenueSummary {
  const span = WINDOW_DAYS[period];
  const window = DAYS.slice(DAYS.length - span);
  const before = DAYS.slice(DAYS.length - 2 * span, DAYS.length - span);
  const current = totals(window, MARGIN_RATE);
  // Per-SKU and per-category figures follow today's mix, scaled to the window.
  const scale = current.revenue / TODAY_REVENUE;
  const facings = new Map(demoStoreState().products.map((product) => [product.sku, product.facings]));
  const skus: SkuRevenue[] = [...TODAY_BY_SKU].map(([sku, { revenue, units }]) => ({
    sku,
    name: DEMO_NAMES[sku] ?? sku,
    revenue: cents(revenue * scale),
    units: Math.round(units * scale),
    facings: facings.get(sku) ?? 0,
  }));
  const categories = new Map<string, number>();
  for (const sku of skus) categories.set(categoryOf(sku.sku), (categories.get(categoryOf(sku.sku)) ?? 0) + sku.revenue);
  const outOfStock = demoStoreState().products.filter((product) => product.shelf_quantity === 0);
  const lostPerDay = outOfStock.reduce((sum, product) => sum + (DEMO_PRICES[product.sku] ?? 0) * LOST_UNITS_PER_DAY, 0);

  const buckets =
    period === REVENUE_PERIOD.Today
      ? Array.from({ length: 24 }, (_, hour) => {
          const start = TODAY.getTime() + hour * HOUR_MS;
          const revenue = SALES.filter((sale) => {
            const at = Date.parse(sale.completed_at);
            return at >= start && at < start + HOUR_MS;
          }).reduce((sum, sale) => sum + sale.total, 0);
          return { start: new Date(start).toISOString(), revenue: cents(revenue) };
        })
      : window.map((day) => ({ start: day.date.toISOString(), revenue: day.revenue }));

  return {
    ...current,
    store_id: STORE_ID,
    period,
    // Stockouts began a few days ago: the longer the window, the less of it they cover.
    lost_to_stockout: cents(lostPerDay * Math.min(span, 4)),
    previous: totals(before, MARGIN_RATE - 0.01),
    bucket_size: period === REVENUE_PERIOD.Today ? BUCKET_SIZE.Hour : BUCKET_SIZE.Day,
    buckets,
    categories: [...categories].map(([category, revenue]) => ({ category, revenue: cents(revenue) })),
    top_skus: [...skus].sort((a, b) => b.revenue - a.revenue).slice(0, 5),
    // Lowest revenue per facing: the shelf space that earns least.
    slow_skus: [...skus].sort((a, b) => a.revenue / Math.max(1, a.facings) - b.revenue / Math.max(1, b.facings)).slice(0, 3),
  };
}

const PROMOTIONS: Promotion[] = [
  {
    id: "PRM-101",
    name: "Breakfast week",
    status: PROMOTION_STATUS.Active,
    kind: PROMOTION_KIND.PercentOff,
    value: 0.15,
    starts_at: "2026-10-06T00:00:00Z",
    ends_at: "2026-10-12T23:59:59Z",
    skus: ["P001", "P008"],
    revenue: 1240.5,
    incremental_revenue: 310.2,
    discount_cost: 186.1,
  },
  {
    id: "PRM-102",
    name: "Chicken breast 2 for 1",
    status: PROMOTION_STATUS.Active,
    kind: PROMOTION_KIND.BuyXGetY,
    value: 1,
    starts_at: "2026-10-08T00:00:00Z",
    ends_at: "2026-10-10T23:59:59Z",
    skus: ["P009"],
    revenue: 512.4,
    incremental_revenue: 96.8,
    discount_cost: 143.8,
  },
  {
    id: "PRM-103",
    name: "Pasta night bundle",
    status: PROMOTION_STATUS.Scheduled,
    kind: PROMOTION_KIND.Bundle,
    value: 3.99,
    starts_at: "2026-10-12T00:00:00Z",
    ends_at: "2026-10-19T23:59:59Z",
    skus: ["P004", "P007"],
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
  },
  {
    id: "PRM-104",
    name: "Frozen peas $1 off",
    status: PROMOTION_STATUS.PendingReview,
    kind: PROMOTION_KIND.AmountOff,
    value: 1,
    starts_at: "2026-10-11T00:00:00Z",
    ends_at: "2026-10-17T23:59:59Z",
    skus: ["P010"],
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
  },
  {
    id: "PRM-105",
    name: "Apple season",
    status: PROMOTION_STATUS.Draft,
    kind: PROMOTION_KIND.PercentOff,
    value: 0.1,
    starts_at: "2026-10-20T00:00:00Z",
    ends_at: "2026-11-02T23:59:59Z",
    skus: ["P011"],
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
  },
  {
    id: "PRM-099",
    name: "Coffee mornings",
    status: PROMOTION_STATUS.Ended,
    kind: PROMOTION_KIND.PercentOff,
    value: 0.2,
    starts_at: "2026-09-22T00:00:00Z",
    ends_at: "2026-09-30T23:59:59Z",
    skus: ["P006"],
    revenue: 860.0,
    incremental_revenue: 205.4,
    discount_cost: 172.0,
  },
];

/** `GET /promotions` for the demo store: totals add up the promotions. */
export function demoPromotions(): PromotionsSummary {
  const promotions = structuredClone(PROMOTIONS);
  const sum = (pick: (promotion: Promotion) => number) => cents(promotions.reduce((total, promotion) => total + pick(promotion), 0));
  return {
    store_id: STORE_ID,
    revenue: sum((promotion) => promotion.revenue),
    incremental_revenue: sum((promotion) => promotion.incremental_revenue),
    discount_cost: sum((promotion) => promotion.discount_cost),
    promotions,
  };
}

/** The API client with revenue and promotions answered from the demo data; everything else still goes to apps/api. */
export const demoClient: RetailTwinClient = {
  ...defaultClient,
  revenue: (period) => Promise.resolve(demoRevenue(period)),
  promotions: () => Promise.resolve(demoPromotions()),
  anomalies: () => Promise.resolve(demoAnomalies()),
  checkouts: (checkoutId) => {
    const summary = demoCheckout(checkoutId);
    if (!summary) {
      // Return empty response for unknown checkout IDs
      return Promise.resolve({
        summary: {
          checkout_id: checkoutId,
          store_id: STORE_ID,
          status: "closed" as const,
          cashier: null,
          shift_started_at: null,
          business_date: "",
          revenue_today: 0,
          transactions_today: 0,
          items_scanned_today: 0,
          queue_length: 0,
          last_transaction_at: null,
        },
        transactions: [],
      });
    }
    return Promise.resolve({ summary, transactions: demoTransactions(checkoutId) });
  },
};
