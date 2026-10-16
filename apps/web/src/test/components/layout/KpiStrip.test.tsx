// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KpiStrip } from "@/components/layout/KpiStrip";
import { REVENUE_TODAY_REFRESH_MS, REVENUE_TODAY_STALE_MS } from "@/constants/app.constant";
import { notify } from "@/core/notify";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoClient } from "@/fixtures/demo/commerce";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import type { RetailTwinClient } from "@/types/api.type";

vi.mock("@/core/notify", () => ({ notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));

MotionGlobalConfig.skipAnimations = true;

const live = demoStoreState();

/** A client whose `GET /revenue` is not served, as apps/api today. A new one per test, so no read is cached. */
const unservedClient = (): RetailTwinClient => ({
  ...demoClient,
  revenue: () => Promise.reject(new Error("404 Not Found")),
});

const tile = (id: string) => screen.getByTestId(`kpi-${id}`);
const valueOf = (id: string) => tile(id).querySelector(".kpi-tile-value")!.textContent;

beforeEach(() => {
  useAnomalyStore.setState(useAnomalyStore.getInitialState(), true);
  useTwinStore.setState({ ...useTwinStore.getInitialState(), status: TWIN_STATUS.Ready }, true);
  vi.mocked(notify.error).mockClear();
});

afterEach(cleanup);

describe("KPI strip", () => {
  it("shows the four tiles from the demo fixtures", async () => {
    useTwinStore.setState({ live, simulation: demoSimulation(live), candidates: demoCandidates(live) });
    useAnomalyStore.getState().setAll(demoAnomalies(live));
    render(<KpiStrip client={{ ...demoClient }} />);

    await waitFor(() => expect(valueOf("revenue")).not.toBe("—"));
    expect(valueOf("revenue")).toMatch(/^\$/);
    const onShelf = live.products.filter((product) => product.shelf_quantity > 0).length;
    expect(within(tile("availability")).getByText(`${onShelf} of ${live.products.length} products`)).toBeTruthy();
    await waitFor(() => expect(valueOf("stockout")).toBe("2"));
    expect(valueOf("impact")).toBe("+0.93");
    expect(tile("impact").title).toContain("projected by simulation-kpi-v1");
    expect(tile("impact").title).toContain("Not measured in the store");
    for (const id of ["revenue", "availability", "stockout", "impact"]) expect(tile(id).dataset.missing).toBeUndefined();
    expect(within(tile("impact")).getByText("Projected impact")).toBeTruthy();
    expect(within(tile("revenue")).getByText("Recorded sales")).toBeTruthy();
  });

  it("gives every tile one basis: recorded revenue, Live stock, projected impact", () => {
    render(<KpiStrip client={unservedClient()} />);
    expect(tile("revenue").dataset.basis).toBe("recorded");
    expect(tile("availability").dataset.basis).toBe("live");
    expect(tile("stockout").dataset.basis).toBe("live");
    expect(tile("impact").dataset.basis).toBe("projected");
  });

  it("keeps the Live Twin tiles when GET /revenue is unavailable", async () => {
    useTwinStore.setState({ live });
    useAnomalyStore.getState().setAll(demoAnomalies(live));
    const client = { ...demoClient, revenue: vi.fn(() => Promise.reject(new Error("503 Service Unavailable"))) };
    render(<KpiStrip client={client} />);
    await waitFor(() => expect(client.revenue).toHaveBeenCalled());
    await act(async () => {});

    expect(valueOf("revenue")).toBe("—");
    expect(tile("revenue").dataset.missing).toBe("notServed");
    expect(tile("revenue").textContent).not.toMatch(/\$0/);
    const onShelf = live.products.filter((product) => product.shelf_quantity > 0).length;
    expect(within(tile("availability")).getByText(`${onShelf} of ${live.products.length} products`)).toBeTruthy();
    await waitFor(() => expect(valueOf("stockout")).toBe("2"));
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("counts the Live Twin, not the open simulation's proposed store, on the Live tiles", () => {
    const proposed = { ...live, products: live.products.map((product) => ({ ...product, shelf_quantity: 10 })) };
    useTwinStore.setState({ live, simulation: { ...demoSimulation(live), state: proposed }, candidates: demoCandidates(live) });
    render(<KpiStrip client={unservedClient()} />);
    const onShelf = live.products.filter((product) => product.shelf_quantity > 0).length;
    expect(onShelf).toBeLessThan(live.products.length);
    expect(within(tile("availability")).getByText(`${onShelf} of ${live.products.length} products`)).toBeTruthy();
  });

  describe("revenue refresh", () => {
    beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] }));
    afterEach(() => vi.useRealTimers());

    it("reads today's revenue again, and stops showing it once it is stale", async () => {
      let up = true;
      const client = {
        ...demoClient,
        revenue: vi.fn((period: Parameters<RetailTwinClient["revenue"]>[0]) => (up ? demoClient.revenue(period) : Promise.reject(new Error("503")))),
      };
      render(<KpiStrip client={client} />);
      await act(async () => {});
      expect(valueOf("revenue")).toMatch(/^\$/);

      up = false;
      await act(() => vi.advanceTimersByTimeAsync(REVENUE_TODAY_REFRESH_MS));
      // One failed read keeps the last good figure while it is fresh.
      expect(valueOf("revenue")).toMatch(/^\$/);

      await act(() => vi.advanceTimersByTimeAsync(REVENUE_TODAY_STALE_MS));
      expect(client.revenue.mock.calls.length).toBeGreaterThan(2);
      expect(valueOf("revenue")).toBe("—");
      expect(tile("revenue").dataset.missing).toBe("stale");
      expect(tile("revenue").title).toBe("GET /revenue has not answered for over 5 minutes, so its last value is no longer shown.");

      up = true;
      await act(() => vi.advanceTimersByTimeAsync(REVENUE_TODAY_REFRESH_MS));
      expect(valueOf("revenue")).toMatch(/^\$/);
      expect(tile("revenue").dataset.missing).toBeUndefined();
    });
  });

  it("shows — with the reason, never 0, when no source is served", async () => {
    const client = unservedClient();
    const revenue = vi.spyOn(client, "revenue");
    render(<KpiStrip client={client} />);
    await waitFor(() => expect(revenue).toHaveBeenCalled());
    await act(async () => {});

    for (const id of ["revenue", "availability", "stockout", "impact"]) {
      expect(valueOf(id)).toBe("—");
      expect(tile(id).textContent).not.toMatch(/\b0(\.0+)?%?\b|\$0/);
    }
    expect(tile("revenue").title).toBe("GET /revenue has not served today's revenue.");
    expect(tile("availability").title).toBe("The Live Twin has not been read yet.");
    expect(tile("stockout").title).toBe("The anomaly feed (GET /anomalies) has not been served.");
    expect(tile("impact").title).toBe("No open simulation for the KPI evaluator to score.");
    // The strip says so itself: a missing route does not toast on every page load.
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("says why each tile is empty when its source served nothing to count", () => {
    useTwinStore.setState({ live: { ...live, products: [] }, simulation: demoSimulation(live), candidates: [] });
    render(<KpiStrip client={unservedClient()} />);
    expect(tile("availability").dataset.missing).toBe("empty");
    expect(tile("availability").title).toBe("The Live Twin serves no products.");
    expect(tile("impact").dataset.missing).toBe("notScored");
    expect(tile("impact").title).toBe("The KPI evaluator has not scored a plan against the baseline.");
  });

  it("shows 0 stockouts once the feed is served with none open", () => {
    useAnomalyStore.getState().setAll({ anomalies: [], total: 0 });
    render(<KpiStrip client={unservedClient()} />);
    expect(valueOf("stockout")).toBe("0");
  });

  it("follows the Live Twin when an ACT restocks a product", async () => {
    useTwinStore.setState({ live });
    render(<KpiStrip client={unservedClient()} />);
    const before = live.products.filter((product) => product.shelf_quantity > 0).length;
    expect(within(tile("availability")).getByText(`${before} of ${live.products.length} products`)).toBeTruthy();

    const restocked = { ...live, products: live.products.map((product) => (product.sku === "P003" ? { ...product, shelf_quantity: 12 } : product)) };
    act(() => useTwinStore.setState({ live: restocked }));
    expect(within(tile("availability")).getByText(`${before + 1} of ${live.products.length} products`)).toBeTruthy();
  });

  it("collapses and opens again", () => {
    render(<KpiStrip client={unservedClient()} />);
    fireEvent.click(screen.getByRole("button", { name: "Hide the business KPIs" }));
    expect(screen.queryByRole("region", { name: "Business KPIs" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Business KPIs" }));
    expect(screen.getByRole("region", { name: "Business KPIs" })).toBeTruthy();
  });
});
