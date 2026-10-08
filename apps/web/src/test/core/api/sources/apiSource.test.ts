import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiSource } from "@/core/api/sources/apiSource";
import { sampleStoreState } from "@/test/sampleState";
import type { RetailTwinClient } from "@/types/api.type";

function fakeClient(store: RetailTwinClient["store"]): RetailTwinClient {
  return { health: vi.fn(), inventory: vi.fn(), store };
}

describe("apiSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads the snapshot from GET /store", async () => {
    const source = createApiSource(fakeClient(async () => sampleStoreState()));
    await expect(source.snapshot()).resolves.toEqual(sampleStoreState());
  });

  it("polls GET /store, reports a failed read, and stops on unsubscribe", async () => {
    const store = vi
      .fn<RetailTwinClient["store"]>()
      .mockResolvedValueOnce(sampleStoreState())
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue(sampleStoreState());
    const onState = vi.fn();
    const onError = vi.fn();
    const unsubscribe = createApiSource(fakeClient(store), 1000).subscribe(onState, onError);

    await vi.advanceTimersByTimeAsync(2000);
    expect(onState).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(new Error("down"));

    unsubscribe();
    await vi.advanceTimersByTimeAsync(5000);
    expect(store).toHaveBeenCalledTimes(2);
  });
});
