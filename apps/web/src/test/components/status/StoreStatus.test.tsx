// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/core/api/client";
import { notify } from "@/core/notify";
import type { HealthResponse, RetailTwinClient } from "@/types/api.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { StoreStatus } from "@/components/status/StoreStatus";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";

vi.mock("@/core/notify", () => ({
  notify: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
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
    ...overrides,
  };
}

beforeEach(() => {
  // The store comes from the scene's live twin, which polls GET /store.
  useTwinStore.setState({ live: store, status: TWIN_STATUS.Ready });
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
