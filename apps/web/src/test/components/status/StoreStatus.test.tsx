// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/core/api/client";
import { notify } from "@/core/notify";
import type { HealthResponse, RetailTwinClient } from "@/types/api.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { StoreStatus } from "@/components/status/StoreStatus";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { STORE_STATUS_ROWS } from "@/constants/app.constant";
import { stockedStoreState } from "@/test/stockedState";

vi.mock("@/core/notify", () => ({
  notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

const product: ProductInventory = {
  store_id: "store-001",
  sku: "P001",
  shelf_id: "A01",
  slot_id: "A01-S01",
  facings: 3,
  shelf_quantity: 8,
  backroom_quantity: 42,
  version: 1,
};

const store: StoreResponse = {
  store_id: "store-001",
  context_version: "store-001:v1",
  version: "v1",
  products: [product],
};

function client(overrides: Partial<RetailTwinClient> = {}): RetailTwinClient {
  return {
    health: vi.fn(async (): Promise<HealthResponse> => ({
      status: "ok",
      service: "retailtwin-api",
      environment: "test",
      store_id: "store-001",
      fixture_loaded: true,
    })),
    store: vi.fn(async () => store),
    inventory: vi.fn(async () => product),
    revenue: vi.fn(),
    promotions: vi.fn(),
    simulations: vi.fn(),
    simulation: vi.fn(),
    candidates: vi.fn(),
    reviewSimulation: vi.fn(),
    anomalies: vi.fn(),
    checkout: vi.fn(),
    flagshipStatus: vi.fn(),
    flagshipReset: vi.fn(),
    flagshipStart: vi.fn(),
    agentEvents: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  // The store comes from the scene's live twin, which polls GET /store.
  useTwinStore.setState({ live: store, status: TWIN_STATUS.Ready });
  useUiStore.getState().select(null);
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new TypeError("offline");
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test("shows the live store and the API health", async () => {
  render(<StoreStatus client={client()} />);

  expect(await screen.findByRole("heading", { name: "store-001" })).toBeTruthy();
  expect(screen.getByText("P001")).toBeTruthy();
  expect(screen.getByText("Context store-001:v1 · version v1")).toBeTruthy();
  expect(screen.getByText("API ok · test · store-001")).toBeTruthy();
});

test("keeps the page up when the API cannot be reached", async () => {
  const failing = client({
    health: vi.fn(async () => {
      throw new ApiError(0, "network_error", "The API is unreachable.");
    }),
  });
  useTwinStore.setState({ live: null, status: TWIN_STATUS.Error });

  render(<StoreStatus client={failing} />);

  await waitFor(() => {
    expect(notify.error).toHaveBeenCalledWith("The API request failed.", expect.any(ApiError));
  });
  expect(screen.getByRole("textbox", { name: "SKU" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "store-001" })).toBeNull();
});

test("shows an inventory error without dropping the store", async () => {
  const api = client({
    inventory: vi.fn(async () => {
      throw new ApiError(404, "sku_not_found", "SKU 'P017' is not in store store-001.");
    }),
  });
  render(<StoreStatus client={api} />);
  expect(await screen.findByRole("heading", { name: "store-001" })).toBeTruthy();

  fireEvent.change(screen.getByRole("textbox", { name: "SKU" }), { target: { value: "P017" } });
  fireEvent.click(screen.getByRole("button", { name: "Look up inventory" }));

  await waitFor(() => {
    expect(notify.error).toHaveBeenCalledWith(
      "Inventory lookup failed.",
      expect.objectContaining({ message: "SKU 'P017' is not in store store-001." }),
    );
  });
  expect(screen.getByRole("heading", { name: "store-001" })).toBeTruthy();
});

test("selects the product GET /inventory/{sku} finds", async () => {
  const api = client();
  render(<StoreStatus client={api} />);
  await screen.findByRole("heading", { name: "store-001" });

  fireEvent.change(screen.getByRole("textbox", { name: "SKU" }), { target: { value: "P001" } });
  fireEvent.click(screen.getByRole("button", { name: "Look up inventory" }));

  await waitFor(() => expect(selectedProductId(useUiStore.getState())).toBe("P001"));
  expect(api.inventory).toHaveBeenCalledWith("P001");
});

test("asks for a SKU before calling the API", async () => {
  const api = client();
  render(<StoreStatus client={api} />);
  await screen.findByRole("heading", { name: "store-001" });

  fireEvent.click(screen.getByRole("button", { name: "Look up inventory" }));

  expect(notify.warning).toHaveBeenCalledWith("Enter a SKU.");
  expect(api.inventory).not.toHaveBeenCalled();
});

test("reads health once, however often the panel reopens, and never fetches the store itself", async () => {
  const api = client();
  const first = render(<StoreStatus client={api} />);
  await screen.findByText("API ok · test · store-001");
  first.unmount();

  render(<StoreStatus client={api} />);
  expect(screen.getByText("API ok · test · store-001")).toBeTruthy();
  expect(api.health).toHaveBeenCalledTimes(1);
  expect(api.store).not.toHaveBeenCalled();
});

test("retries health on the next open after a failed read", async () => {
  const api = client({
    health: vi
      .fn<RetailTwinClient["health"]>()
      .mockRejectedValueOnce(new ApiError(0, "network_error", "The API is unreachable."))
      .mockResolvedValue({
        status: "ok",
        service: "retailtwin-api",
        environment: "test",
        store_id: "store-001",
        fixture_loaded: true,
      }),
  });
  const first = render(<StoreStatus client={api} />);
  await waitFor(() => expect(notify.error).toHaveBeenCalledTimes(1));
  first.unmount();

  render(<StoreStatus client={api} />);
  expect(await screen.findByText("API ok · test · store-001")).toBeTruthy();
  expect(api.health).toHaveBeenCalledTimes(2);
});

test("lists products one per line, out and low stock first, and opens the rest in a dialog", async () => {
  const many: StoreResponse = { ...store, products: stockedStoreState().products };
  useTwinStore.setState({ live: many, status: TWIN_STATUS.Ready });
  useUiStore.getState().select(null);
  render(<StoreStatus client={client()} />);
  await screen.findByRole("heading", { name: "store-001" });

  const rows = () => screen.getAllByRole("button", { name: /^Show P\d+ in the store$/ });
  // P003 and P010 are out, P004 and P007 low; then the rest by SKU.
  expect(rows().map((row) => row.getAttribute("aria-label")!.split(" ")[1])).toEqual([
    "P003",
    "P010",
    "P004",
    "P007",
    "P001",
  ]);
  expect(rows()).toHaveLength(STORE_STATUS_ROWS);

  fireEvent.click(screen.getByRole("button", { name: `Show all ${many.products.length}` }));
  const dialog = await screen.findByRole("dialog");
  const dialogRows = () => within(dialog).getAllByRole("row", { name: /^Show P\d+ in the store$/ });
  expect(dialogRows()).toHaveLength(many.products.length);

  // Filter by state, then search within it.
  fireEvent.click(within(dialog).getByRole("radio", { name: "Out of stock" }));
  expect(dialogRows().map((row) => row.getAttribute("aria-label"))).toEqual([
    "Show P003 in the store",
    "Show P010 in the store",
  ]);
  fireEvent.change(within(dialog).getByRole("searchbox", { name: "Search SKU, shelf, or slot" }), {
    target: { value: "oc01" },
  });
  expect(dialogRows()).toHaveLength(1);

  // A row selects the product in the 3D view and closes the dialog.
  fireEvent.click(dialogRows()[0]);
  expect(selectedProductId(useUiStore.getState())).toBe("P010");
  // The modal leaves the DOM after its exit animation, which a slow CI runner stretches past 1 s.
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 5000 });
});

test("selects a product in the 3D view from its line", async () => {
  useUiStore.getState().select(null);
  render(<StoreStatus client={client()} />);
  const row = await screen.findByRole("button", { name: "Show P001 in the store" });
  fireEvent.click(row);
  expect(selectedProductId(useUiStore.getState())).toBe("P001");
  expect(row.getAttribute("aria-pressed")).toBe("true");
});

test("reads GET /health from apps/api by default", async () => {
  render(<StoreStatus />);
  await waitFor(() => expect(notify.error).toHaveBeenCalledWith("The API request failed.", expect.anything()));
  expect(vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url)).pathname)).toContain("/health");
});

test("under ?twin=demo, calls no API and looks a SKU up in the demo store", async () => {
  window.history.replaceState(null, "", "/?twin=demo");
  render(<StoreStatus />);
  expect(await screen.findByRole("heading", { name: "store-001" })).toBeTruthy();
  expect(screen.queryByText(/^API /)).toBeNull();

  fireEvent.change(screen.getByRole("textbox", { name: "SKU" }), { target: { value: "p001" } });
  fireEvent.click(screen.getByRole("button", { name: "Look up inventory" }));
  expect(screen.getByText("P001 on A01 / A01-S01: 8 on shelf, 42 in the backroom.")).toBeTruthy();
  expect(selectedProductId(useUiStore.getState())).toBe("P001");
  expect(fetch).not.toHaveBeenCalled();
  window.history.replaceState(null, "", "/");
});
