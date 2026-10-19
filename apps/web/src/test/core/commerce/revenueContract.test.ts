import { describe, expect, it } from "vitest";
import { ContractError, parseRevenueResponse, toRevenueSummary } from "@/core/commerce/revenueContract";
import { formatWindow, revenueQuery, revenueSearch, startOfDay } from "@/core/commerce/revenueWindow";
import { REVENUE_PERIOD } from "@/enums/commerce.enum";

const iso = (instant: number) => new Date(instant).toISOString();

describe("revenueQuery", () => {
  const now = new Date("2026-10-18T12:43:37Z");

  it("maps today to hourly and the longer windows to daily, from the first moment of their first day to now", () => {
    expect(revenueQuery(REVENUE_PERIOD.Today, now, "UTC")).toEqual({ period: "hourly", start: "2026-10-18T00:00:00.000Z", end: "2026-10-18T12:43:37.000Z" });
    expect(revenueQuery(REVENUE_PERIOD.Week, now, "UTC")).toEqual({ period: "daily", start: "2026-10-12T00:00:00.000Z", end: "2026-10-18T12:43:37.000Z" });
    expect(revenueQuery(REVENUE_PERIOD.Month, now, "UTC")).toEqual({ period: "daily", start: "2026-09-19T00:00:00.000Z", end: "2026-10-18T12:43:37.000Z" });
  });

  it("never sends the lens's window names", () => {
    for (const period of Object.values(REVENUE_PERIOD)) {
      const search = new URLSearchParams(revenueSearch(revenueQuery(period, now, "UTC")));
      expect(["hourly", "daily"]).toContain(search.get("period"));
      expect(search.get("start")).toBeTruthy();
      expect(search.get("end")).toBe(now.toISOString());
    }
  });

  it("starts today at the store's local midnight, not the browser's or UTC's", () => {
    // 03:00 on 19 October in Ho Chi Minh City (UTC+7): today began at 17:00 UTC on the 18th.
    const late = new Date("2026-10-18T20:00:00Z");
    expect(revenueQuery(REVENUE_PERIOD.Today, late, "Asia/Ho_Chi_Minh").start).toBe("2026-10-18T17:00:00.000Z");
    expect(revenueQuery(REVENUE_PERIOD.Today, late, "UTC").start).toBe("2026-10-18T00:00:00.000Z");
  });

  it("counts calendar days across a daylight-saving change, not 24-hour blocks", () => {
    // New York springs forward on 8 March 2026: the 7 days to 10 March start at EST midnight on the 4th.
    const after = new Date("2026-03-10T15:00:00Z");
    expect(revenueQuery(REVENUE_PERIOD.Week, after, "America/New_York").start).toBe("2026-03-04T05:00:00.000Z");
    expect(revenueQuery(REVENUE_PERIOD.Today, after, "America/New_York").start).toBe("2026-03-10T04:00:00.000Z");
  });

  it("includes the first moment of the day, and puts now at the end", () => {
    const midnight = new Date("2026-10-18T00:00:00Z");
    expect(revenueQuery(REVENUE_PERIOD.Today, midnight, "UTC")).toEqual({
      period: "hourly",
      start: "2026-10-18T00:00:00.000Z",
      end: "2026-10-18T00:00:00.000Z",
    });
    const justBefore = new Date("2026-10-17T23:59:59.999Z");
    expect(revenueQuery(REVENUE_PERIOD.Today, justBefore, "UTC").start).toBe("2026-10-17T00:00:00.000Z");
  });
});

describe("startOfDay", () => {
  it("is local midnight on both sides of New York's daylight-saving changes", () => {
    expect(iso(startOfDay({ year: 2026, month: 3, day: 8 }, "America/New_York"))).toBe("2026-03-08T05:00:00.000Z");
    expect(iso(startOfDay({ year: 2026, month: 3, day: 9 }, "America/New_York"))).toBe("2026-03-09T04:00:00.000Z");
    expect(iso(startOfDay({ year: 2026, month: 11, day: 1 }, "America/New_York"))).toBe("2026-11-01T04:00:00.000Z");
    expect(iso(startOfDay({ year: 2026, month: 11, day: 2 }, "America/New_York"))).toBe("2026-11-02T05:00:00.000Z");
  });

  it("is the first wall time after the jump when the clocks skip midnight", () => {
    // Santiago skips 00:00–01:00 on 7 September 2025: the day starts at 01:00 (UTC−3), 04:00 UTC.
    expect(iso(startOfDay({ year: 2025, month: 9, day: 7 }, "America/Santiago"))).toBe("2025-09-07T04:00:00.000Z");
  });
});

/** A `RevenueResponse` as apps/api serves it, for an hourly read of the morning of 18 October. */
const response = (extra: Record<string, unknown> = {}) => ({
  store_id: "store-001",
  period: "hourly",
  start: "2026-10-18T00:00:00Z",
  end: "2026-10-18T03:30:00Z",
  total_revenue: 42.5,
  total_transactions: 3,
  total_items_sold: 5,
  avg_transaction_value: 14.17,
  currency: "USD",
  buckets: [{ timestamp: "2026-10-18T01:00:00Z", revenue: 42.5, transactions: 3, items_sold: 5 }],
  ...extra,
});
const query = { period: "hourly", start: "2026-10-18T00:00:00.000Z", end: "2026-10-18T03:30:00.000Z" } as const;

describe("parseRevenueResponse", () => {
  it("takes a RevenueResponse as served", () => {
    expect(parseRevenueResponse(response())).toMatchObject({ store_id: "store-001", period: "hourly", total_revenue: 42.5 });
  });

  it.each([
    ["not an object", [], "response"],
    ["no store", response({ store_id: "" }), "store_id"],
    ["the lens's window name as period", response({ period: "today" }), "period"],
    ["an unreadable start", response({ start: "yesterday" }), "start"],
    ["revenue as text", response({ total_revenue: "42.5" }), "total_revenue"],
    ["negative revenue", response({ total_revenue: -1 }), "total_revenue"],
    ["fractional transactions", response({ total_transactions: 1.5 }), "total_transactions"],
    ["no currency", response({ currency: null }), "currency"],
    ["buckets not a list", response({ buckets: {} }), "buckets"],
    ["a bucket without a timestamp", response({ buckets: [{ revenue: 1, transactions: 1, items_sold: 1 }] }), "buckets[0]"],
  ])("refuses %s", (_name, raw, field) => {
    expect(() => parseRevenueResponse(raw)).toThrow(ContractError);
    try {
      parseRevenueResponse(raw);
    } catch (error) {
      expect((error as ContractError).field).toBe(field);
    }
  });
});

describe("toRevenueSummary", () => {
  it("keeps what was served, fills the hours with no sales with 0, and leaves what was not served null", () => {
    const summary = toRevenueSummary(parseRevenueResponse(response()), REVENUE_PERIOD.Today, query);
    expect(summary).toMatchObject({
      store_id: "store-001",
      period: "today",
      start: "2026-10-18T00:00:00Z",
      end: "2026-10-18T03:30:00Z",
      currency: "USD",
      revenue: 42.5,
      transactions: 3,
      average_basket: 14.17,
      items_sold: 5,
      bucket_size: "hour",
      margin_rate: null,
      lost_to_stockout: null,
      previous: null,
      categories: null,
      top_skus: null,
      slow_skus: null,
    });
    expect(summary.buckets).toEqual([
      { start: "2026-10-18T00:00:00.000Z", revenue: 0 },
      { start: "2026-10-18T01:00:00.000Z", revenue: 42.5 },
      { start: "2026-10-18T02:00:00.000Z", revenue: 0 },
      { start: "2026-10-18T03:00:00.000Z", revenue: 0 },
    ]);
  });

  it("lays the days of a daily read on a calendar grid", () => {
    const daily = response({
      period: "daily",
      start: "2026-10-12T00:00:00Z",
      end: "2026-10-18T12:00:00Z",
      buckets: [{ timestamp: "2026-10-14T00:00:00Z", revenue: 42.5, transactions: 3, items_sold: 5 }],
    });
    const summary = toRevenueSummary(parseRevenueResponse(daily), REVENUE_PERIOD.Week, { ...query, period: "daily" });
    expect(summary.bucket_size).toBe("day");
    expect(summary.buckets).toHaveLength(7);
    expect(summary.buckets[2]).toEqual({ start: "2026-10-14T00:00:00.000Z", revenue: 42.5 });
  });

  it("refuses an answer for another grain, another currency, or a bucket off the grid", () => {
    expect(() => toRevenueSummary(parseRevenueResponse(response({ period: "daily" })), REVENUE_PERIOD.Today, query)).toThrow("period");
    expect(() => toRevenueSummary(parseRevenueResponse(response({ currency: "EUR" })), REVENUE_PERIOD.Today, query)).toThrow("currency");
    const offGrid = response({ buckets: [{ timestamp: "2026-10-18T01:30:00Z", revenue: 1, transactions: 1, items_sold: 1 }] });
    expect(() => toRevenueSummary(parseRevenueResponse(offGrid), REVENUE_PERIOD.Today, query)).toThrow("buckets[0].timestamp");
    const outside = response({ buckets: [{ timestamp: "2026-10-18T09:00:00Z", revenue: 1, transactions: 1, items_sold: 1 }] });
    expect(() => toRevenueSummary(parseRevenueResponse(outside), REVENUE_PERIOD.Today, query)).toThrow("buckets");
  });
});

describe("formatWindow", () => {
  it("names the window in the store's time zone, whatever the viewer's", () => {
    // ICU spaces the dash with thin spaces; compare with plain ones.
    const plain = (text: string) => text.replace(/\s/g, " ");
    expect(plain(formatWindow("2026-10-18T00:00:00Z", "2026-10-18T13:16:00Z", "UTC"))).toBe("Oct 18, 00:00 – 13:16 UTC");
    expect(plain(formatWindow("2026-10-12T00:00:00Z", "2026-10-18T13:16:00Z", "UTC"))).toBe("Oct 12, 00:00 UTC – Oct 18, 13:16 UTC");
    expect(plain(formatWindow("2026-10-18T17:00:00Z", "2026-10-18T20:00:00Z", "Asia/Ho_Chi_Minh"))).toBe("Oct 19, 00:00 – 03:00 GMT+7");
  });
});
