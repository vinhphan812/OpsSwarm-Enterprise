import { useMemo } from "react";
import type { ProductIssue } from "@/core/api/validate";
import { twinIssues } from "@/core/twin/twinIssues";
import { useActiveState, useShownSimulation } from "@/hooks/activeTwin.hook";
import { useTwinStore } from "@/state/twin.store";

const NO_ISSUES: ProductIssue[] = [];

/**
 * Products of the state on screen that the scene leaves out, kept in step with the twin
 * store. Contract issues belong to the live state, so the Simulation view lists only its
 * own unplaceable products.
 */
export function useTwinIssues(): ProductIssue[] {
  const twin = useActiveState();
  const simulating = useShownSimulation() !== null;
  const liveIssues = useTwinStore((state) => state.issues);
  const contractIssues = simulating ? NO_ISSUES : liveIssues;
  return useMemo(() => twinIssues(twin, contractIssues), [twin, contractIssues]);
}
