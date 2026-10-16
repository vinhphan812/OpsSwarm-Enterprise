import { useMemo } from "react";
import { aiChanges, type AiChanges } from "@/core/twin/aiChanges";
import { diffStates, isEmptyDiff, type StateDiff } from "@/core/twin/stateDiff";
import { useAnomalyStore } from "@/state/anomaly.store";
import { activeState, shownSimulation, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { Anomaly } from "@/types/anomaly.type";

const NO_ANOMALIES: Anomaly[] = [];

/** The twin state on screen: Live, or the simulation's proposal in the Simulation view. */
export function useActiveState() {
  const viewMode = useUiStore((state) => state.viewMode);
  return useTwinStore((twin) => activeState(twin, viewMode));
}

/** The simulation on screen, or null while the scene shows Live. */
export function useShownSimulation() {
  const viewMode = useUiStore((state) => state.viewMode);
  return useTwinStore((twin) => shownSimulation(twin, viewMode));
}

/**
 * Everything the proposal on screen changes against Live, for as long as it is on screen
 * (unlike `useRecentChanges`, which fades). Null in the Live view, or when it changes nothing.
 */
export function useProposalChanges(): StateDiff | null {
  const simulation = useShownSimulation();
  const live = useTwinStore((twin) => twin.live);
  return useMemo(() => {
    if (!simulation || !live) return null;
    const diff = diffStates(live, simulation.state);
    return isEmptyDiff(diff) ? null : diff;
  }, [simulation, live]);
}

/** The AI CHANGES of the proposal on screen against Live; null in the Live view. */
export function useProposalAiChanges(): AiChanges | null {
  const simulation = useShownSimulation();
  const live = useTwinStore((twin) => twin.live);
  return useMemo(() => (simulation && live ? aiChanges(live, simulation.state) : null), [simulation, live]);
}

/**
 * Open anomalies to show. They describe the Live Twin, so the Simulation view shows none:
 * a halo on a proposed state would claim a problem the proposal may already fix.
 */
export function useShownAnomalies(): Anomaly[] {
  const anomalies = useAnomalyStore((state) => state.anomalies);
  return useShownSimulation() ? NO_ANOMALIES : anomalies;
}
