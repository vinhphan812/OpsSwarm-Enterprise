import { describe, expect, it } from "vitest";
import { BUCKET_SIZE, REVENUE_PERIOD } from "@/enums/commerce.enum";
import { STOCK_KIND } from "@/enums/scene.enum";
import { emptyPromotions, emptyRevenue } from "@/fixtures/commerceFixture";

const now = new Date(2026, 9, 8, 15, 30);

describe("emptyRevenue", () => {
  it("covers today hour by hour from midnight, all at 0", () => {
    const summary = emptyRevenue("store-001", REVENUE_PERIOD.Today, now);
    expect(summary.bucket_size).toBe(BUCKET_SIZE.Hour);
    expect(summary.buckets).toHaveLength(24);
    expect(new Date(summary.buckets[0].start)).toEqual(new Date(2026, 9, 8));
    expect(summary.buckets.every((bucket) => bucket.revenue === 0)).toBe(true);
    expect(summary.revenue).toBe(0);
  });

  it("ends a longer window with today", () => {
    const summary = emptyRevenue("store-001", REVENUE_PERIOD.Week, now);
    expect(summary.bucket_size).toBe(BUCKET_SIZE.Day);
    expect(summary.buckets).toHaveLength(7);
    expect(new Date(summary.buckets.at(-1)!.start)).toEqual(new Date(2026, 9, 8));
  });

  it("lists every store category", () => {
    const categories = (emptyRevenue("store-001", REVENUE_PERIOD.Month, now).categories ?? []).map((c) => c.category);
    expect(categories).toEqual(Object.values(STOCK_KIND));
  });
});

it("emptyPromotions has no programs", () => {
  expect(emptyPromotions("store-001")).toMatchObject({ store_id: "store-001", promotions: [], revenue: 0 });
});
