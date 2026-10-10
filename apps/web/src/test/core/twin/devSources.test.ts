// @vitest-environment jsdom
import { createElement } from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiSource } from "@/core/api/sources/apiSource";
import { isDemoMode } from "@/core/twin/demoMode";
import { pickSimulationSource, pickSource } from "@/core/twin/devSources";
import { DemoBadge } from "@/components/twin/DemoBadge";
import { demoStoreState } from "@/fixtures/demo/store";
import { useCheckoutSummary, useCheckoutTransactions } from "@/hooks/checkout.hook";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import type { TwinSource } from "@/core/api/sources/TwinSource";

/** The apps/api twin, here one that cannot be reached. */
const apiSource = vi.hoisted<TwinSource>(() => ({
  snapshot: () => Promise.reject(new Error("The API is unreachable.")),
  subscribe: () => () => {},
}));

vi.mock("@/core/api/sources/apiSource", () => ({ createApiSource: vi.fn(() => apiSource) }));

const at = (url: string) => window.history.replaceState(null, "", url);

beforeEach(() => {
  vi.mocked(createApiSource).mockClear();
  useAnomalyStore.setState({ anomalies: [] });
  useTwinStore.setState({ simulation: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  at("/");
});

describe("pickSource", () => {
  it("reads the Live Twin from apps/api without a ?twin= override", () => {
    at("/");
    expect(pickSource()).toBe(apiSource);
    expect(createApiSource).toHaveBeenCalledTimes(1);
  });

  it("swaps in the demo store and its anomalies under ?twin=demo in development", async () => {
    at("/?twin=demo");
    const source = pickSource();
    expect(source).not.toBe(apiSource);
    expect(createApiSource).not.toHaveBeenCalled();
    await expect(source.snapshot()).resolves.toMatchObject({ products: demoStoreState().products });
    expect(useAnomalyStore.getState().anomalies.length).toBeGreaterThan(0);
    expect(useTwinStore.getState().simulation).toMatchObject({
      simulation_id: "sim-demo-001",
      base_context_version: demoStoreState().context_version,
    });
  });

  it("never turns on demo mode in a production build", () => {
    vi.stubEnv("DEV", false);
    for (const mode of ["demo", "memory", "fixture", "offline", "slow", "flaky"]) {
      at(`/?twin=${mode}`);
      expect(pickSource()).toBe(apiSource);
      expect(isDemoMode()).toBe(false);
    }
    expect(useAnomalyStore.getState().anomalies).toEqual([]);
    expect(useTwinStore.getState().simulation).toBeNull();
  });

  it("keeps demo anomalies, simulations, checkouts and badges out of the apps/api path, even when it fails", async () => {
    at("/");
    await expect(pickSource().snapshot()).rejects.toThrow("The API is unreachable.");
    expect(useAnomalyStore.getState().anomalies).toEqual([]);
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(useCheckoutSummary("CK01")).toBeNull();
    expect(useCheckoutTransactions("CK01", true)).toEqual([]);
    expect(render(createElement(DemoBadge)).container.innerHTML).toBe("");
  });
});

describe("pickSimulationSource", () => {
  it("reads simulations from apps/api alongside the apps/api Live Twin", () => {
    at("/");
    expect(pickSimulationSource()).not.toBeNull();
    at("/?twin=unknown");
    expect(pickSimulationSource()).not.toBeNull();
    vi.stubEnv("DEV", false);
    at("/?twin=demo");
    expect(pickSimulationSource()).not.toBeNull();
  });

  it("leaves simulations to the console and the demo fixture under a ?twin= dev twin", () => {
    for (const mode of ["demo", "memory", "fixture", "offline", "slow", "flaky"]) {
      at(`/?twin=${mode}`);
      expect(pickSimulationSource()).toBeNull();
    }
  });
});
