import { describe, expect, test, vi } from "vitest";
import { ApiError, createClient } from "@/core/api/client";
import type { HealthResponse } from "@/types/api.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

const health: HealthResponse = {
  status: "ok",
  service: "retailtwin-api",
  environment: "test",
  store_id: "store-001",
  fixture_loaded: true,
};

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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("createClient", () => {
  test("reads health, store, and inventory", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/health")) return jsonResponse(health);
      if (url.endsWith("/store")) return jsonResponse(store);
      if (url.endsWith("/inventory/P001")) return jsonResponse(product);
      return jsonResponse({ error: { code: "http_error", message: "missing" } }, 404);
    });
    const client = createClient("http://127.0.0.1:8000/", fetchImpl);

    await expect(client.health()).resolves.toEqual(health);
    await expect(client.store()).resolves.toEqual(store);
    await expect(client.inventory("P001")).resolves.toEqual(product);
    expect(String(fetchImpl.mock.calls[0][0])).toBe("http://127.0.0.1:8000/health");
  });

  test("encodes the SKU and surfaces the API message", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).endsWith("/inventory/NO%20SUCH")) {
        throw new Error(`unexpected ${String(input)}`);
      }
      return jsonResponse(
        { error: { code: "sku_not_found", message: "SKU 'NO SUCH' is not in store store-001." } },
        404,
      );
    });
    const client = createClient("http://127.0.0.1:8000", fetchImpl);

    await expect(client.inventory("NO SUCH")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "sku_not_found",
      message: "SKU 'NO SUCH' is not in store store-001.",
    });
    expect(String(fetchImpl.mock.calls[0][0])).toBe("http://127.0.0.1:8000/inventory/NO%20SUCH");
  });

  test("turns a network failure into a controlled error", async () => {
    const client = createClient(
      "http://127.0.0.1:8000",
      vi.fn(async () => {
        throw new TypeError("connect ECONNREFUSED");
      }),
    );

    await expect(client.health()).rejects.toEqual(new ApiError(0, "network_error", "The API is unreachable."));
  });

  test("does not crash when the error body is not JSON", async () => {
    const client = createClient(
      "http://127.0.0.1:8000",
      vi.fn(async () => new Response("nope", { status: 502 })),
    );

    await expect(client.store()).rejects.toEqual(new ApiError(502, "request_failed", "Request failed (502)."));
  });
});

test("asks the revenue and promotions routes for their payloads", async () => {
  const fetchImpl = vi.fn(async (_url: RequestInfo | URL) => jsonResponse({}));
  const client = createClient("http://127.0.0.1:8000/", fetchImpl);
  await client.revenue("7d");
  await client.promotions();
  expect(fetchImpl.mock.calls.map(([url]) => String(url))).toEqual([
    "http://127.0.0.1:8000/revenue?period=7d",
    "http://127.0.0.1:8000/promotions",
  ]);
});

test("asks the simulation routes for the open runs and one run, encoding its id", async () => {
  const fetchImpl = vi.fn(async (_url: RequestInfo | URL) => jsonResponse({}));
  const client = createClient("http://127.0.0.1:8000/", fetchImpl);
  await client.simulations();
  await client.simulation("sim 1");
  expect(fetchImpl.mock.calls.map(([url]) => String(url))).toEqual([
    "http://127.0.0.1:8000/simulations?status=open",
    "http://127.0.0.1:8000/simulations/sim%201",
  ]);
});
