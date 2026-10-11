import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { useTwinStore } from "@/state/twin.store";

describe("twin store", () => {
  beforeEach(() => useTwinStore.setState(useTwinStore.getInitialState(), true));
  afterEach(() => vi.useRealTimers());

  it("setLive replaces the live state", () => {
    const state = sampleStoreState();
    useTwinStore.getState().setLive(state);

    expect(useTwinStore.getState().live).toBe(state);
    expect(useTwinStore.getState().simulation).toBeNull();
  });

  it("records no change for the first live state", () => {
    useTwinStore.getState().setLive(sampleStoreState());
    expect(useTwinStore.getState().liveChange).toBeNull();
  });

  it("records the diff and its time when a live state changes something", () => {
    vi.useFakeTimers({ now: 1000 });
    const first = sampleStoreState();
    const next = { ...first, products: first.products.map((p) => (p.sku === "P002" ? { ...p, facings: 3 } : p)) };
    useTwinStore.getState().setLive(first);
    useTwinStore.getState().setLive(next);

    expect(useTwinStore.getState().liveChange).toEqual({
      diff: expect.objectContaining({ facings: [{ sku: "P002", before: 2, after: 3 }] }),
      at: 1000,
      before: first,
    });
    expect(useTwinStore.getState().liveChange?.before).toBe(first);
  });

  it("keeps the last change when a live state changes nothing", () => {
    const first = sampleStoreState();
    const next = { ...first, products: first.products.map((p) => (p.sku === "P002" ? { ...p, facings: 3 } : p)) };
    useTwinStore.getState().setLive(first);
    useTwinStore.getState().setLive(next);
    const change = useTwinStore.getState().liveChange;

    useTwinStore.getState().setLive({ ...next, context_version: `${next.context_version}+1` });
    expect(useTwinStore.getState().liveChange).toBe(change);
  });
});
