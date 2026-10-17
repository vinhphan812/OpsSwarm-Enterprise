import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiSource } from "@/core/api/sources/apiSource";
import { sampleStoreState } from "@/test/sampleState";
import type { RetailTwinClient } from "@/types/api.type";

function fakeClient(store: RetailTwinClient["store"]): RetailTwinClient {
  return { health: vi.fn(), inventory: vi.fn(), revenue: vi.fn(), promotions: vi.fn(), simulations: vi.fn(), simulation: vi.fn(), candidates: vi.fn(), reviewSimulation: vi.fn(), anomalies: vi.fn(), checkout: vi.fn(), store };
}

describe("apiSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads the snapshot from GET /store", async () => {
    const source = createApiSource(fakeClient(async () => sampleStoreState()));
    await expect(source.snapshot()).resolves.toEqual(sampleStoreState());
  });

  it("polls GET /store and stops on unsubscribe", async () => {
    const store = vi.fn<RetailTwinClient["store"]>().mockResolvedValue(sampleStoreState());
    const onState = vi.fn();
    const unsubscribe = createApiSource(fakeClient(store), 1000).subscribe(onState);

    await vi.advanceTimersByTimeAsync(2000);
    expect(onState).toHaveBeenCalledTimes(2);

    unsubscribe();
    await vi.advanceTimersByTimeAsync(5000);
    expect(store).toHaveBeenCalledTimes(2);
  });

  it("waits longer after each failed read, up to the cap, and resets after a good one", async () => {
    const store = vi
      .fn<RetailTwinClient["store"]>()
      .mockRejectedValueOnce(new Error("down"))
      .mockRejectedValueOnce(new Error("down"))
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue(sampleStoreState());
    const onError = vi.fn();
    createApiSource(fakeClient(store), 1000, 3000).subscribe(vi.fn(), onError);

    // Reads at 1s, then 2s later, then 3s later (capped), then 3s later again.
    await vi.advanceTimersByTimeAsync(1000);
    expect(store).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(store).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(store).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(3000);
    expect(store).toHaveBeenCalledTimes(3);
    expect(onError).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(3000);
    expect(store).toHaveBeenCalledTimes(4);
    // Back to the normal interval after the good read.
    await vi.advanceTimersByTimeAsync(1000);
    expect(store).toHaveBeenCalledTimes(5);
  });
});
