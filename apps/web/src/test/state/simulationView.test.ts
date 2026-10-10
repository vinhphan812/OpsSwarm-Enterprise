import { beforeEach, describe, expect, it } from "vitest";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { activeState, shownSimulation, useTwinStore } from "@/state/twin.store";

describe("Live and Simulation twin state", () => {
  beforeEach(() => useTwinStore.setState(useTwinStore.getInitialState(), true));

  it("keeps Live as it is when a simulation opens or closes", () => {
    const live = demoStoreState();
    const before = structuredClone(live);
    useTwinStore.getState().setLive(live);

    useTwinStore.getState().setSimulation(demoSimulation(live));
    expect(useTwinStore.getState().live).toBe(live);
    expect(live).toEqual(before);

    useTwinStore.getState().setSimulation(null);
    expect(useTwinStore.getState().live).toBe(live);
  });

  it("shows the proposal only in the Simulation view, and Live otherwise", () => {
    const live = demoStoreState();
    const simulation = demoSimulation(live);
    const twin = { live, simulation };

    expect(activeState(twin, VIEW_MODE.Live)).toBe(live);
    expect(shownSimulation(twin, VIEW_MODE.Live)).toBeNull();
    expect(activeState(twin, VIEW_MODE.Simulation)).toBe(simulation.state);
    expect(shownSimulation(twin, VIEW_MODE.Simulation)).toBe(simulation);
  });

  it("falls back to Live in the Simulation view when no simulation is open", () => {
    const live = demoStoreState();
    expect(activeState({ live, simulation: null }, VIEW_MODE.Simulation)).toBe(live);
    expect(activeState({ live: null, simulation: null }, VIEW_MODE.Simulation)).toBeNull();
  });
});
