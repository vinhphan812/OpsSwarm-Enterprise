import { beforeEach, describe, expect, it } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { useTwinStore } from "@/state/twin.store";

describe("twin store", () => {
  beforeEach(() => useTwinStore.setState({ live: null, simulation: null }));

  it("setLive replaces the live state", () => {
    const state = sampleStoreState();
    useTwinStore.getState().setLive(state);

    expect(useTwinStore.getState().live).toBe(state);
    expect(useTwinStore.getState().simulation).toBeNull();
  });
});
