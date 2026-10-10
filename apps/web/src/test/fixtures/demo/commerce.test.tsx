// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PROMOTION_STATUSES, REVENUE_PERIOD, REVENUE_PERIODS } from "@/enums/commerce.enum";
import { demoCheckout } from "@/fixtures/demo/checkouts";
import { DEMO_NAMES, demoPromotions, demoRevenue } from "@/fixtures/demo/commerce";
import { demoStoreState } from "@/fixtures/demo/store";
import { usePromotions, useRevenue } from "@/hooks/commerce.hook";

vi.mock("@/core/notify", () => ({ notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() } }));

afterEach(() => window.history.replaceState(null, "", "/"));

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
const stocked = new Set(demoStoreState().products.map((product) => product.sku));

describe("demo revenue", () => {
  it("adds today up from the demo checkouts' sales", () => {
    const today = demoRevenue(REVENUE_PERIOD.Today);
    const lanes = ["CK01", "CK02", "CK03"].map((id) => demoCheckout(id)!);
    expect(today.revenue).toBeCloseTo(sum(lanes.map((lane) => lane.revenue_today)), 2);
    expect(today.transactions).toBe(sum(lanes.map((lane) => lane.transactions_today)));
    expect(today.average_basket).toBeCloseTo(today.revenue / today.transactions, 2);
    expect(today.buckets).toHaveLength(24);
    expect(sum(today.buckets.map((bucket) => bucket.revenue))).toBeCloseTo(today.revenue, 1);
  });

  for (const period of REVENUE_PERIODS) {
    it(`is consistent for ${period}`, () => {
      const report = demoRevenue(period);
      expect(report.period).toBe(period);
      expect(report.buckets).toHaveLength(period === REVENUE_PERIOD.Today ? 24 : period === REVENUE_PERIOD.Week ? 7 : 30);
      expect(sum(report.buckets.map((bucket) => bucket.revenue))).toBeCloseTo(report.revenue, 0);
      expect(sum(report.categories.map((category) => category.revenue))).toBeCloseTo(report.revenue, 0);
      expect(report.previous.revenue).toBeGreaterThan(0);
      expect(report.lost_to_stockout).toBeGreaterThan(0);
      expect(report.margin_rate).toBeGreaterThan(0);

      const top = report.top_skus.map((sku) => sku.revenue);
      expect(top).toEqual([...top].sort((a, b) => b - a));
      for (const sku of [...report.top_skus, ...report.slow_skus]) {
        expect(stocked.has(sku.sku)).toBe(true);
        expect(sku.name).toBe(DEMO_NAMES[sku.sku]);
      }
    });
  }

  it("grows with the window, the same on every call", () => {
    const [today, week, month] = REVENUE_PERIODS.map((period) => demoRevenue(period).revenue);
    expect(week).toBeGreaterThan(today);
    expect(month).toBeGreaterThan(week);
    expect(demoRevenue(REVENUE_PERIOD.Week)).toEqual(demoRevenue(REVENUE_PERIOD.Week));
  });
});

describe("demo promotions", () => {
  it("add their totals up, cover every status, and run on stocked SKUs", () => {
    const report = demoPromotions();
    expect(report.revenue).toBeCloseTo(sum(report.promotions.map((promotion) => promotion.revenue)), 2);
    expect(report.incremental_revenue).toBeCloseTo(sum(report.promotions.map((promotion) => promotion.incremental_revenue)), 2);
    expect(report.discount_cost).toBeCloseTo(sum(report.promotions.map((promotion) => promotion.discount_cost)), 2);
    expect(new Set(report.promotions.map((promotion) => promotion.status))).toEqual(new Set(PROMOTION_STATUSES));
    for (const promotion of report.promotions) {
      expect(promotion.skus.every((sku) => stocked.has(sku))).toBe(true);
      expect(Date.parse(promotion.ends_at)).toBeGreaterThan(Date.parse(promotion.starts_at));
    }
  });
});

describe("the Revenue and Promotions lenses under ?twin=demo", () => {
  it("read the demo reports", async () => {
    window.history.replaceState(null, "", "/?twin=demo");
    const revenue = renderHook(() => useRevenue(REVENUE_PERIOD.Today));
    await waitFor(() => expect(revenue.result.current.revenue).toBeCloseTo(demoRevenue(REVENUE_PERIOD.Today).revenue, 2));
    const promotions = renderHook(() => usePromotions());
    await waitFor(() => expect(promotions.result.current.promotions).toHaveLength(demoPromotions().promotions.length));
  });
});
