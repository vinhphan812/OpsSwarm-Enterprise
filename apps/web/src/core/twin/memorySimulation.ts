import type { MemoryTwin } from "@/core/api/sources/memorySource";
import { simulationOf, DEMO_ACTIONS } from "@/fixtures/demo/simulation";
import { useTwinStore } from "@/state/twin.store";
import type { SimulationAction } from "@/types/simulation.type";

/**
 * Simulations on the in-memory twin, driven from the browser console under
 * `?twin=memory|demo` (`twin.simulate()`, `twin.commit()`, `twin.discard()`). They stand
 * in for the simulation API and the guarded commit. Development builds only.
 */

let runs = 0;

/** Opens a simulation of `actions` (the demo actions by default) on the twin's current state. Returns its id. */
export function openSimulation(twin: MemoryTwin, actions: SimulationAction[] = DEMO_ACTIONS): string {
  runs += 1;
  const simulation = simulationOf(twin.current(), actions, `sim-memory-${String(runs).padStart(3, "0")}`);
  useTwinStore.getState().setSimulation(simulation);
  return simulation.simulation_id;
}

/**
 * Commits the open simulation the way the backend would after the guard: refused when
 * Live has moved on since the simulation started (REFRESH_REQUIRED). The proposed state
 * is written to the twin, which pushes it to the live feed; the web app's Live view
 * changes only through that feed. Returns the new live context version.
 */
export function commitSimulation(twin: MemoryTwin): string {
  const { simulation, setSimulation } = useTwinStore.getState();
  if (!simulation) throw new Error("No simulation is open.");
  const live = twin.current();
  if (live.context_version !== simulation.base_context_version) {
    throw new Error(
      `REFRESH_REQUIRED: ${simulation.simulation_id} started from ${simulation.base_context_version}, Live is now ${live.context_version}.`,
    );
  }
  const committed = twin.update(() => structuredClone(simulation.state));
  setSimulation(null);
  return committed.context_version;
}

/** Drops the open simulation without touching Live. */
export function discardSimulation() {
  useTwinStore.getState().setSimulation(null);
}
