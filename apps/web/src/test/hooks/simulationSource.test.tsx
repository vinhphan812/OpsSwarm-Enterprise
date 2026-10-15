// @vitest-environment jsdom
import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SimulationSource } from "@/core/api/sources/simulationSource";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { useSimulationSource } from "@/hooks/simulationSource.hook";
import { useTwinStore } from "@/state/twin.store";

/** A source the test drives by hand. */
function manualSource() {
  const calls: Parameters<SimulationSource["subscribe"]>[] = [];
  const source: SimulationSource = { subscribe: (...args) => (calls.push(args), () => undefined) };
  return { source, last: () => calls.at(-1)! };
}

afterEach(() => {
  cleanup();
  useTwinStore.setState(useTwinStore.getInitialState(), true);
});

describe("useSimulationSource", () => {
  it("fills the run and its candidates, flags a failed read, and clears the flag on the next good read", () => {
    const { source, last } = manualSource();
    renderHook(() => useSimulationSource(source));
    const [onUpdate, onError, onRead] = last();
    const simulation = demoSimulation();
    const candidates = demoCandidates();

    onUpdate(simulation, candidates);
    expect(useTwinStore.getState().simulation).toBe(simulation);
    expect(useTwinStore.getState().candidates).toBe(candidates);

    onError?.(new Error("503"));
    expect(useTwinStore.getState().simulationReadFailed).toBe(true);
    // The last served values stay.
    expect(useTwinStore.getState().candidates).toBe(candidates);

    onRead?.();
    expect(useTwinStore.getState().simulationReadFailed).toBe(false);
  });
});
