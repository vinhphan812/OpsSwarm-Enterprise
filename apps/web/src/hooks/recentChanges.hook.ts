import { useEffect, useMemo, useReducer } from "react";
import { CHANGE_CUE_MS } from "@/constants/twin.constant";
import { diffStates, isEmptyDiff, type FacingsChange, type QuantityChange } from "@/core/twin/stateDiff";
import { VIEW_MODE } from "@/enums/ui.enum";
import { shownSimulation, useTwinStore, type RecentChange } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { StoreResponse } from "@/types/twin.type";

/** `live` against a proposal the scene has just left, timed from when it left; null when that changes nothing. */
function backToLive(proposal: StoreResponse | undefined, live: StoreResponse, at: number): RecentChange | null {
  if (!proposal || at <= 0) return null;
  const diff = diffStates(proposal, live);
  return isEmptyDiff(diff) ? null : { diff, at, before: proposal };
}

/** The latest of `changes`. */
function newest(changes: (RecentChange | null)[]): RecentChange | null {
  return changes.reduce<RecentChange | null>((latest, change) => (change && (!latest || change.at > latest.at) ? change : latest), null);
}

/**
 * The change the scene should cue, or null once it is older than `CHANGE_CUE_MS`.
 * Live view: the last Live → Live change. Simulation view: the proposal against Live,
 * from when the view was opened or the proposal last changed. The diff is against the
 * current Live state, so Live changes since the simulation's base show up too.
 *
 * Leaving a proposal is a change too: back in Live from the Simulation view, or after the
 * proposal on screen was rejected or discarded (`twin.store.leftProposal`), Live is cued
 * against the proposal, so its moves play back to where Live has them. Whichever happened
 * last is shown. An approval leaves no such cue; Live changes through its feed.
 */
export function useRecentChanges(): RecentChange | null {
  const viewMode = useUiStore((ui) => ui.viewMode);
  const viewChangedAt = useUiStore((ui) => ui.viewChangedAt);
  const live = useTwinStore((twin) => twin.live);
  const liveChange = useTwinStore((twin) => twin.liveChange);
  // The proposal the Simulation view shows, a selected candidate's included, whichever view is on.
  const open = useTwinStore((twin) => shownSimulation(twin, VIEW_MODE.Simulation));
  const simulation = useTwinStore((twin) => shownSimulation(twin, viewMode));
  const simulationChangedAt = useTwinStore((twin) => twin.simulationChangedAt);
  const leftProposal = useTwinStore((twin) => twin.leftProposal);

  const change = useMemo(() => {
    if (!live) return simulation ? null : liveChange;
    if (!simulation) {
      // A proposal that opened after the switch to Live was never on screen.
      const leftView = open && viewChangedAt >= simulationChangedAt ? backToLive(open.state, live, viewChangedAt) : null;
      const dropped = leftProposal ? backToLive(leftProposal.state, live, leftProposal.at) : null;
      return newest([liveChange, leftView, dropped]);
    }
    const diff = diffStates(live, simulation.state);
    return isEmptyDiff(diff) ? null : { diff, at: Math.max(viewChangedAt, simulationChangedAt), before: live };
  }, [simulation, open, live, liveChange, leftProposal, viewChangedAt, simulationChangedAt]);

  const [, expire] = useReducer((count: number) => count + 1, 0);
  const remaining = change ? change.at + CHANGE_CUE_MS - Date.now() : 0;
  const recent = remaining > 0;

  useEffect(() => {
    if (!recent) return;
    const timer = setTimeout(expire, remaining);
    return () => clearTimeout(timer);
    // Re-arm only for a new change; `remaining` shrinks on every render.
  }, [change, recent]);

  return recent ? change : null;
}

/** `sku`'s facings change, while it is recent; null otherwise. */
export function useFacingsChange(sku: string | null): FacingsChange | null {
  const change = useRecentChanges();
  return change?.diff.facings.find((item) => item.sku === sku) ?? null;
}

/** The slot `sku` was moved from, while the move is recent; null otherwise. */
export function useMovedFrom(sku: string | null): string | null {
  const change = useRecentChanges();
  return change?.diff.moved.find((item) => item.sku === sku)?.from.slot_id ?? null;
}

/** `sku`'s shelf and backroom deltas, while they are recent; null otherwise. */
export function useQuantityChange(sku: string | null): QuantityChange | null {
  const change = useRecentChanges();
  return change?.diff.quantity.find((item) => item.sku === sku) ?? null;
}
