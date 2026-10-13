// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CHANGE_CUE_MS } from "@/constants/twin.constant";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useRecentChanges } from "@/hooks/recentChanges.hook";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { sampleStoreState } from "@/test/sampleState";
import type { StoreResponse } from "@/types/twin.type";

/** `state` one context version later, with P001's facings set. */
function withFacings(state: StoreResponse, facings: number): StoreResponse {
  return {
    ...state,
    context_version: `${state.context_version}+${facings}`,
    products: state.products.map((product) => (product.sku === "P001" ? { ...product, facings } : product)),
  };
}

describe("useRecentChanges", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useTwinStore.setState(useTwinStore.getInitialState(), true);
    useUiStore.setState(useUiStore.getInitialState(), true);
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("cues a Live change, then lets it fade after CHANGE_CUE_MS", () => {
    const first = sampleStoreState();
    useTwinStore.getState().setLive(first);
    const { result } = renderHook(() => useRecentChanges());
    expect(result.current).toBeNull();

    act(() => useTwinStore.getState().setLive(withFacings(first, 5)));
    expect(result.current?.diff.facings).toEqual([{ sku: "P001", before: first.products[0].facings, after: 5 }]);

    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS - 1));
    expect(result.current).not.toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBeNull();
  });

  it("cues the proposal against Live in the Simulation view, and leaves Live alone", () => {
    const live = demoStoreState();
    const before = structuredClone(live);
    useTwinStore.getState().setLive(live);
    useTwinStore.getState().setSimulation(demoSimulation(live));
    const { result } = renderHook(() => useRecentChanges());
    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS));
    expect(result.current).toBeNull();

    act(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    const diff = result.current?.diff;
    expect(diff?.moved.map((move) => move.sku)).toEqual(["P005", "P007", "P008"]);
    expect(diff?.moved).toContainEqual({ sku: "P007", from: { shelf_id: "B02", slot_id: "B02-S20" }, to: { shelf_id: "B02", slot_id: "B02-S22" } });
    expect(diff?.facings.map((change) => change.sku)).toEqual(["P004"]);
    expect(result.current?.before).toBe(live);
    expect(diff?.quantity).toEqual([{ sku: "P003", shelfDelta: 12, backroomDelta: -12 }]);
    expect(useTwinStore.getState().live).toBe(live);
    expect(live).toEqual(before);

    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS));
    expect(result.current).toBeNull();

    // Back in Live, the proposal's changes play back to Live; Live itself is untouched.
    act(() => useUiStore.getState().setViewMode(VIEW_MODE.Live));
    expect(result.current?.diff.moved).toContainEqual({
      sku: "P007",
      from: { shelf_id: "B02", slot_id: "B02-S22" },
      to: { shelf_id: "B02", slot_id: "B02-S20" },
    });
    expect(result.current?.before).toBe(useTwinStore.getState().simulation?.state);
    expect(useTwinStore.getState().live).toBe(live);
    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS));
    expect(result.current).toBeNull();
  });

  it("plays a rejected proposal back to Live, but not one that was never on screen", () => {
    const live = demoStoreState();
    useTwinStore.getState().setLive(live);
    const simulation = demoSimulation(live);
    useTwinStore.getState().setSimulation(simulation);
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    const { result } = renderHook(() => useRecentChanges());
    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS));

    act(() => {
      useTwinStore.getState().leaveProposal(simulation.state);
      useTwinStore.getState().setSimulation(null);
    });
    expect(result.current?.diff.moved.map((move) => move.to.slot_id)).toEqual(["A03-S22", "B02-S20", "C01-S21"]);
    act(() => useUiStore.getState().setViewMode(VIEW_MODE.Live));
    expect(result.current?.diff.moved.map((move) => move.to.slot_id)).toEqual(["A03-S22", "B02-S20", "C01-S21"]);
    act(() => vi.advanceTimersByTime(CHANGE_CUE_MS));
    expect(result.current).toBeNull();

    // A proposal that opens while Live is on screen is not cued in Live.
    act(() => useTwinStore.getState().setSimulation(demoSimulation(live)));
    expect(result.current).toBeNull();
  });
});
