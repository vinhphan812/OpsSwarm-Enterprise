import { useEffect } from "react";
import type { SimulationSource } from "@/core/api/sources/simulationSource";
import { useTwinStore } from "@/state/twin.store";

/**
 * Keeps `twin.store.simulation` on the open simulation from `source` until unmount.
 * Only `simulation` is written, never `live`. A failed read keeps the last simulation
 * and shows no toast: apps/api serves no simulations yet (TODO(BE), #26), and the
 * source backs off on its own. Without a source (a `?twin=` dev twin), the console
 * drives simulations instead.
 */
export function useSimulationSource(source: SimulationSource | null) {
  useEffect(() => {
    if (!source) return;
    return source.subscribe((simulation, candidates = []) => {
      useTwinStore.getState().setSimulation(simulation);
      useTwinStore.getState().setCandidates(candidates);
    });
  }, [source]);
}
