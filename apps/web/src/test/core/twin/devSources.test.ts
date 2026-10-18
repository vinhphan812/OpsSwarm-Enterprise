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
  useAnomalyStore.setState({ anomalies: [], readError: null });
  useTwinStore.setState({ simulation: null, candidates: [], selectedCandidateId: null });
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

  it("opens the demo on /demo in development, and apps/api on / and /live", () => {
    at("/demo");
    expect(isDemoMode()).toBe(true);
    expect(pickSource()).not.toBe(apiSource);
    for (const path of ["/", "/live"]) {
      at(path);
      expect(isDemoMode()).toBe(false);
      expect(pickSource()).toBe(apiSource);
    }
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
    expect(useTwinStore.getState().candidates.map((item) => item.simulation_id)).toEqual(
      expect.arrayContaining(["sim-demo-001"]),
    );
    expect(useTwinStore.getState().candidates.length).toBeGreaterThanOrEqual(2);
  });

  it("lets the console fail the demo anomaly read and read it again", () => {
    at("/?twin=demo");
    pickSource();
    const count = useAnomalyStore.getState().anomalies.length;
    const twin = (window as unknown as { twin: { failAnomalies: (message?: string) => void; reloadAnomalies: () => void } }).twin;

    twin.failAnomalies();
    expect(useAnomalyStore.getState()).toMatchObject({ readError: "GET /anomalies did not answer." });
    expect(useAnomalyStore.getState().anomalies).toHaveLength(count);

    twin.reloadAnomalies();
    expect(useAnomalyStore.getState().readError).toBeNull();
    expect(useAnomalyStore.getState().anomalies).toHaveLength(count);
  });

  it("never turns on demo mode in a production build", () => {
    vi.stubEnv("DEV", false);
    for (const url of ["/demo", "/", "/live", ...["demo", "memory", "fixture", "offline", "slow", "flaky"].map((mode) => `/?twin=${mode}`)]) {
      at(url);
      expect(pickSource()).toBe(apiSource);
      expect(isDemoMode()).toBe(false);
    }
    expect(useAnomalyStore.getState().anomalies).toEqual([]);
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(useTwinStore.getState().candidates).toEqual([]);
  });

  it("reads apps/api on /live whatever its ?twin=, in development and in a demo build", () => {
    for (const env of [{ DEV: true, VITE_ALLOW_DEMO: "" }, { DEV: false, VITE_ALLOW_DEMO: "true" }]) {
      vi.stubEnv("DEV", env.DEV);
      vi.stubEnv("VITE_ALLOW_DEMO", env.VITE_ALLOW_DEMO);
      for (const mode of ["demo", "memory", "fixture", "offline", "slow", "flaky"]) {
        at(`/live?twin=${mode}`);
        expect(isDemoMode()).toBe(false);
        expect(pickSource()).toBe(apiSource);
        expect(pickSimulationSource()).not.toBeNull();
      }
    }
  });

  it("opens only the demo in a production build made with VITE_ALLOW_DEMO=true, at /, /demo or ?twin=demo", async () => {
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_ALLOW_DEMO", "true");
    for (const mode of ["memory", "fixture", "offline", "slow", "flaky"]) {
      at(`/?twin=${mode}`);
      expect(pickSource()).toBe(apiSource);
      expect(isDemoMode()).toBe(false);
    }
    // The live twin stays reachable on /live.
    at("/live");
    expect(pickSource()).toBe(apiSource);
    expect(isDemoMode()).toBe(false);
    expect(pickSimulationSource()).not.toBeNull();
    for (const path of ["/", "/demo"]) {
      at(path);
      expect(isDemoMode()).toBe(true);
      expect(pickSource()).not.toBe(apiSource);
    }
    at("/?twin=demo");
    const source = pickSource();
    expect(source).not.toBe(apiSource);
    expect(isDemoMode()).toBe(true);
    expect(pickSimulationSource()).toBeNull();
    await expect(source.snapshot()).resolves.toMatchObject({ products: demoStoreState().products });
  });

  it("keeps demo anomalies, simulations, checkouts and badges out of the apps/api path, even when it fails", async () => {
    at("/");
    await expect(pickSource().snapshot()).rejects.toThrow("The API is unreachable.");
    expect(useAnomalyStore.getState().anomalies).toEqual([]);
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(useTwinStore.getState().candidates).toEqual([]);
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
