import { describe, expect, it, vi } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import type { StoreResponse } from "@/core/api/types";
import { patchProduct } from "@/core/api/sources/memorySource";
import { InvalidTwinStateError } from "@/core/api/validate";
import { connectTwin } from "@/core/twin/twinConnection";

const at = (revision: number): StoreResponse => ({
  ...sampleStoreState(),
  context_version: `store-001:v${revision}`,
  version: `v${revision}`,
});

/** A source whose snapshot and feed the test drives by hand. */
function controlledSource() {
  let resolveSnapshot!: (state: StoreResponse) => void;
  let rejectSnapshot!: (error: unknown) => void;
  let push!: (state: StoreResponse) => void;
  let fail!: (error: unknown) => void;
  const unsubscribe = vi.fn();
  const source: TwinSource = {
    snapshot: () =>
      new Promise((resolve, reject) => {
        resolveSnapshot = resolve;
        rejectSnapshot = reject;
      }),
    subscribe: (onState, onError) => {
      push = onState;
      fail = (error) => onError?.(error);
      return unsubscribe;
    },
  };
  return {
    source,
    unsubscribe,
    resolveSnapshot: (s: StoreResponse) => resolveSnapshot(s),
    rejectSnapshot: (e: unknown) => rejectSnapshot(e),
    push: (s: StoreResponse) => push(s),
    fail: (e: unknown) => fail(e),
  };
}

function recorder() {
  return { onState: vi.fn(), onStatus: vi.fn(), onFeedError: vi.fn() };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("connectTwin", () => {
  it("goes loading, then ready with the snapshot", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    expect(events.onStatus).toHaveBeenLastCalledWith("loading");

    twin.resolveSnapshot(at(1));
    await flush();
    expect(events.onState).toHaveBeenCalledWith(at(1), []);
    expect(events.onStatus).toHaveBeenLastCalledWith("ready");
  });

  it("reports an error when the first load fails", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    const error = new Error("offline");
    twin.rejectSnapshot(error);
    await flush();
    expect(events.onStatus).toHaveBeenLastCalledWith("error", error);
    expect(events.onState).not.toHaveBeenCalled();
  });

  it("keeps a pushed update when an older snapshot lands after it", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.push(at(5));
    twin.resolveSnapshot(at(4));
    await flush();
    expect(events.onState).toHaveBeenCalledTimes(1);
    expect(events.onState).toHaveBeenCalledWith(at(5), []);
  });

  it("ignores updates that are not newer than the last one", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.resolveSnapshot(at(3));
    await flush();
    twin.push(at(3));
    twin.push(at(2));
    twin.push(at(7));
    expect(events.onState.mock.calls.map(([state]) => state.context_version)).toEqual(["store-001:v3", "store-001:v7"]);
  });

  it("keeps the last state on screen when the feed drops after loading", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.resolveSnapshot(at(1));
    await flush();
    twin.fail(new Error("socket closed"));
    expect(events.onFeedError).toHaveBeenCalledTimes(1);
    expect(events.onStatus).not.toHaveBeenCalledWith("error", expect.anything());
  });

  it("fails the load when the first payload is not a store state", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.resolveSnapshot({ ...at(1), products: undefined } as unknown as StoreResponse);
    await flush();
    expect(events.onStatus).toHaveBeenLastCalledWith("error", expect.any(InvalidTwinStateError));
    expect(events.onState).not.toHaveBeenCalled();
  });

  it("keeps the last state when a later payload is not a store state", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.resolveSnapshot(at(1));
    await flush();
    twin.push({ ...at(2), store_id: "" });
    expect(events.onState).toHaveBeenCalledTimes(1);
    expect(events.onFeedError).toHaveBeenCalledWith(expect.any(InvalidTwinStateError));
  });

  it("delivers the valid products and reports the broken ones", async () => {
    const twin = controlledSource();
    const events = recorder();
    connectTwin(twin.source, events);
    twin.resolveSnapshot(patchProduct(at(1), "P001", { slot_id: null }));
    await flush();
    const [state, issues] = events.onState.mock.calls[0];
    expect(state.products.some((p: { sku: string }) => p.sku === "P001")).toBe(false);
    expect(issues).toEqual([{ sku: "P001", code: "unassigned" }]);
  });

  it("unsubscribes on cleanup and delivers nothing afterwards", async () => {
    const twin = controlledSource();
    const events = recorder();
    const cleanup = connectTwin(twin.source, events);
    cleanup();
    expect(twin.unsubscribe).toHaveBeenCalledTimes(1);
    twin.resolveSnapshot(at(1));
    twin.push(at(2));
    await flush();
    expect(events.onState).not.toHaveBeenCalled();
  });
});
