import { useMemo } from "react";
import type { ProductIssue } from "@/core/api/validate";
import { diffStates } from "@/core/twin/stateDiff";
import { twinIssues } from "@/core/twin/twinIssues";
import { useActiveState, useShownSimulation } from "@/hooks/activeTwin.hook";
import { unitsDrawn } from "@/scene/entities/stock/Stock";
import { sceneOf } from "@/scene/layout";
import { useTwinStore } from "@/state/twin.store";

const NO_ISSUES: ProductIssue[] = [];

/**
 * Products of the state on screen that the scene leaves out, kept in step with the twin
 * store. Contract issues belong to the live state, so the Simulation view lists only its
 * own unplaceable products.
 *
 * Inconsistent transfers come from the change that led to the state on screen: the last
 * Live → Live change, kept until the next one, or the proposal against Live.
 */
export function useTwinIssues(): ProductIssue[] {
  const twin = useActiveState();
  const simulation = useShownSimulation();
  const live = useTwinStore((state) => state.live);
  const liveChange = useTwinStore((state) => state.liveChange);
  const liveIssues = useTwinStore((state) => state.issues);
  const contractIssues = simulation ? NO_ISSUES : liveIssues;
  const change = useMemo(
    () => (simulation ? (live ? diffStates(live, simulation.state) : null) : (liveChange?.diff ?? null)),
    [simulation, live, liveChange],
  );
  return useMemo(() => twinIssues(twin, contractIssues, change), [twin, contractIssues, change]);
}

/** Shelf units of `sku` in the state on screen that its facings cannot hold, so the scene does not draw them; 0 when all are drawn. */
export function useUnitsNotShown(sku: string | null): number {
  const twin = useActiveState();
  const product = sku ? twin?.products.find((item) => item.sku === sku) : undefined;
  if (!twin || !product) return 0;
  return Math.max(0, product.shelf_quantity - (unitsDrawn(sceneOf(twin).store).get(product.sku) ?? 0));
}
