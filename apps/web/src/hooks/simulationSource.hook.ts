import { useEffect } from "react";
import type { SimulationSource } from "@/core/api/sources/simulationSource";
import { useTwinStore } from "@/state/twin.store";

/**
 * Keeps `twin.store.simulation` on the open simulation from `source` until unmount.
 * Only `simulation` is written, never `live`. A failed read keeps the last simulation
 * and shows no toast, since the source backs off on its own; it sets
 * `simulationReadFailed`, so the candidate comparison can say its values are the last
 * served, and the next good read clears it. Without a source (a `?twin=` dev twin), the console
 * drives simulations instead.
 */
export function useSimulationSource(source: SimulationSource | null) {
  useEffect(() => {
    if (!source) return;
    const twin = useTwinStore.getState;
    return source.subscribe(
      (simulation, candidates = []) => {
        twin().setSimulation(simulation);
        twin().setCandidates(candidates);
      },
      () => twin().setSimulationReadFailed(true),
      () => twin().setSimulationReadFailed(false),
    );
  }, [source]);
}
