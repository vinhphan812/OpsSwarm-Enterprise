// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { parseStoreState } from "@/core/api/validate";
import { isDemoMode } from "@/core/twin/demoMode";
import { ANOMALY_KIND, ANOMALY_SEVERITIES } from "@/enums/anomaly.enum";
import { PAYMENT_METHODS } from "@/enums/checkout.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { DEMO_PRICES, demoCheckout, demoTransactions } from "@/fixtures/demo/checkouts";
import { demoStoreState } from "@/fixtures/demo/store";
import { useCheckoutSummary, useCheckoutTransactions } from "@/hooks/checkout.hook";
import { toSceneStore } from "@/scene/layout";

afterEach(() => window.history.replaceState(null, "", "/"));

describe("demo mode", () => {
  it("is on only under ?twin=demo", () => {
    expect(isDemoMode()).toBe(false);
    window.history.replaceState(null, "", "/?twin=memory");
    expect(isDemoMode()).toBe(false);
    window.history.replaceState(null, "", "/?twin=demo");
    expect(isDemoMode()).toBe(true);
  });

  it("feeds the checkout hooks, which stay empty otherwise", () => {
    expect(useCheckoutSummary("CK01")).toBeNull();
    expect(useCheckoutTransactions("CK01", true)).toEqual([]);
    window.history.replaceState(null, "", "/?twin=demo");
    expect(useCheckoutSummary("CK01")).toEqual(demoCheckout("CK01"));
    expect(useCheckoutTransactions("CK01", true)).toHaveLength(demoCheckout("CK01")!.transactions_today);
    expect(useCheckoutTransactions("CK01", false)).toEqual([]);
  });
});

describe("demo store", () => {
  it("passes the GET /store contract and places every product", () => {
    const { state, issues } = parseStoreState(demoStoreState());
    expect(issues).toEqual([]);
    expect(toSceneStore(state).issues).toEqual([]);
  });
});

describe("demo anomalies", () => {
  it("point at products of the store, where they stand, and agree with their stock", () => {
    const state = demoStoreState();
    const { anomalies, context_version } = demoAnomalies(state);
    expect(anomalies.length).toBeGreaterThan(0);
    expect(context_version).toBe(state.context_version);
    for (const anomaly of anomalies) {
      const product = state.products.find((item) => item.sku === anomaly.sku)!;
      expect(product).toMatchObject({ shelf_id: anomaly.shelf_id, slot_id: anomaly.slot_id });
      if (anomaly.kind === ANOMALY_KIND.Stockout) expect(product.shelf_quantity).toBe(0);
      if (anomaly.kind === ANOMALY_KIND.LowStock) expect(product.shelf_quantity).toBeLessThan(product.facings);
    }
    expect(anomalies.some((anomaly) => anomaly.sku === "P001")).toBe(false);
  });

  it("put a visible halo on the shelves at every severity", () => {
    const state = demoStoreState();
    const { anomalies } = demoAnomalies(state);
    const onShelf = (sku: string) => state.products.find((item) => item.sku === sku)!.shelf_quantity;
    for (const severity of ANOMALY_SEVERITIES) {
      expect(anomalies.some((anomaly) => anomaly.severity === severity && onShelf(anomaly.sku) > 0)).toBe(true);
    }
  });
});

describe("demo checkouts", () => {
  for (const id of ["CK01", "CK02", "CK03"]) {
    it(`add ${id}'s figures up from its sales, and each sale from its lines`, () => {
      const summary = demoCheckout(id)!;
      const sales = demoTransactions(id);
      expect(sales).toHaveLength(summary.transactions_today);
      expect(sales.reduce((sum, sale) => sum + sale.total, 0)).toBeCloseTo(summary.revenue_today, 2);
      expect(sales.reduce((sum, sale) => sum + sale.items, 0)).toBe(summary.items_scanned_today);
      expect(sales[0].completed_at).toBe(summary.last_transaction_at);
      const times = sales.map((sale) => Date.parse(sale.completed_at));
      expect(times).toEqual([...times].sort((a, b) => b - a));
      for (const sale of sales) {
        expect(PAYMENT_METHODS).toContain(sale.payment_method);
        expect(sale.lines.reduce((sum, line) => sum + line.quantity, 0)).toBe(sale.items);
        expect(sale.lines.reduce((sum, line) => sum + line.line_total, 0)).toBeCloseTo(sale.total, 2);
        for (const line of sale.lines) expect(line.unit_price).toBe(DEMO_PRICES[line.sku]);
      }
    });
  }

  it("sell only SKUs the demo store stocks, the same on every load", () => {
    const stocked = new Set(demoStoreState().products.map((product) => product.sku));
    expect(Object.keys(DEMO_PRICES).every((sku) => stocked.has(sku))).toBe(true);
    expect(demoTransactions("CK01")).toEqual(demoTransactions("CK01"));
    expect(demoCheckout("CK99")).toBeNull();
  });
});
