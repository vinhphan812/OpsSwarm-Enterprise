import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryTwin, patchProduct, type MemoryTwin } from "@/core/api/sources/memorySource";
import { commitSimulation, createMemoryReviewer, discardSimulation, openSimulation } from "@/core/twin/memorySimulation";
import { ACTION_TYPE, GUARD_VERDICT, REVIEW_DECISION, REVIEW_REASON, SIMULATION_STATUS } from "@/enums/simulation.enum";
import { demoStoreState } from "@/fixtures/demo/store";
import { VIEW_MODE } from "@/enums/ui.enum";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { Simulation } from "@/types/simulation.type";
import type { StoreResponse } from "@/types/twin.type";

const sku = (state: StoreResponse, id: string) => state.products.find((product) => product.sku === id)!;

/** Replaces the open run's proposal under the same id, as a re-evaluation would. Returns the new one. */
function replaceProposal(simulation: Simulation): Simulation {
  const replaced = { ...simulation, state: { ...simulation.state, context_version: `${simulation.state.context_version}-r2` } };
  useTwinStore.getState().setSimulation(replaced);
  return replaced;
}

describe("simulations on the memory twin", () => {
  let twin: MemoryTwin;
  let pushed: StoreResponse[];

  beforeEach(() => {
    useTwinStore.setState(useTwinStore.getInitialState(), true);
    twin = createMemoryTwin(demoStoreState());
    pushed = [];
    twin.source.subscribe((state) => pushed.push(state));
  });

  it("opens a simulation without touching Live", () => {
    const before = twin.current();
    openSimulation(twin);

    const simulation = useTwinStore.getState().simulation!;
    expect(simulation.base_context_version).toBe(before.context_version);
    expect(sku(simulation.state, "P003")).toMatchObject({ shelf_quantity: 12, backroom_quantity: 6 });
    expect(twin.current()).toEqual(before);
    expect(pushed).toEqual([]);
  });

  it("simulates the actions it is given", () => {
    openSimulation(twin, [{ type: ACTION_TYPE.ChangeFacings, sku: "P001", facings: 5 }]);
    const simulation = useTwinStore.getState().simulation!;
    expect(simulation.actions).toHaveLength(1);
    expect(sku(simulation.state, "P001").facings).toBe(5);
    expect(sku(simulation.state, "P003").shelf_quantity).toBe(0);
  });

  it("commits through the live feed and closes the simulation", () => {
    openSimulation(twin);
    const version = commitSimulation(twin);

    expect(useTwinStore.getState().simulation).toBeNull();
    expect(pushed).toHaveLength(1);
    expect(pushed[0].context_version).toBe(version);
    expect(version).not.toBe(demoStoreState().context_version);
    expect(sku(pushed[0], "P007")).toMatchObject({ shelf_id: "B02", slot_id: "B02-S22" });
  });

  it("refuses to commit once Live has moved on (REFRESH_REQUIRED), and leaves Live alone", () => {
    openSimulation(twin);
    twin.update((state) => patchProduct(state, "P002", { shelf_quantity: 9 }));
    const live = twin.current();

    expect(() => commitSimulation(twin)).toThrow("REFRESH_REQUIRED");
    expect(twin.current()).toEqual(live);
    expect(useTwinStore.getState().simulation).not.toBeNull();
  });

  it("discards a simulation without touching Live", () => {
    const before = twin.current();
    openSimulation(twin);
    discardSimulation();
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(twin.current()).toEqual(before);
    expect(() => commitSimulation(twin)).toThrow("No simulation is open.");
    // Not on screen, so nothing is played back.
    expect(useTwinStore.getState().leftProposal).toBeNull();
  });

  it("keeps a discarded proposal that was on screen, so the scene can play it back to Live", () => {
    openSimulation(twin);
    const proposal = useTwinStore.getState().simulation!.state;
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    discardSimulation();
    expect(useTwinStore.getState().leftProposal?.state).toBe(proposal);
    useUiStore.setState(useUiStore.getInitialState(), true);
  });

  it("accepts through the guard: ALLOW commits through the live feed", async () => {
    openSimulation(twin);
    const simulation = useTwinStore.getState().simulation!;
    const result = await createMemoryReviewer(twin)(simulation, REVIEW_DECISION.Approve);

    expect(result).toEqual({
      simulation_id: simulation.simulation_id,
      decision: REVIEW_DECISION.Approve,
      status: SIMULATION_STATUS.Committed,
      verdict: GUARD_VERDICT.Allow,
      reason_code: null,
      live_context_version: pushed[0].context_version,
    });
    expect(pushed).toHaveLength(1);
    expect(useTwinStore.getState().simulation).toBeNull();
  });

  it("answers REFRESH_REQUIRED to an accept once Live has moved on, and keeps the run open", async () => {
    openSimulation(twin);
    const simulation = useTwinStore.getState().simulation!;
    twin.update((state) => patchProduct(state, "P002", { shelf_quantity: 9 }));
    const live = twin.current();

    const result = await createMemoryReviewer(twin)(simulation, REVIEW_DECISION.Approve);
    expect(result).toMatchObject({
      status: SIMULATION_STATUS.Evaluated,
      verdict: GUARD_VERDICT.RefreshRequired,
      reason_code: REVIEW_REASON.LiveMoved,
      live_context_version: null,
    });
    expect(twin.current()).toEqual(live);
    expect(useTwinStore.getState().simulation).toBe(simulation);
  });

  it("rejects without touching Live", async () => {
    const before = twin.current();
    openSimulation(twin);
    const simulation = useTwinStore.getState().simulation!;

    const result = await createMemoryReviewer(twin)(simulation, REVIEW_DECISION.Reject);
    expect(result).toMatchObject({ status: SIMULATION_STATUS.Rejected, verdict: null });
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(twin.current()).toEqual(before);
    expect(pushed).toEqual([]);
  });

  it("refuses to review a run that is no longer open", async () => {
    openSimulation(twin);
    const stale = useTwinStore.getState().simulation!;
    openSimulation(twin);
    await expect(createMemoryReviewer(twin)(stale, REVIEW_DECISION.Approve)).rejects.toThrow(`${stale.simulation_id} is not open.`);
    expect(pushed).toEqual([]);
  });

  it("refuses to reject a proposal that was replaced under the same run id, and keeps the run open", async () => {
    const before = twin.current();
    openSimulation(twin);
    const reviewed = useTwinStore.getState().simulation!;
    const replaced = replaceProposal(reviewed);

    const result = await createMemoryReviewer(twin)(reviewed, REVIEW_DECISION.Reject);
    expect(result).toEqual({
      simulation_id: reviewed.simulation_id,
      decision: REVIEW_DECISION.Reject,
      status: SIMULATION_STATUS.Evaluated,
      verdict: null,
      reason_code: REVIEW_REASON.ProposalChanged,
      live_context_version: null,
    });
    expect(useTwinStore.getState().simulation).toBe(replaced);
    expect(twin.current()).toEqual(before);
    expect(pushed).toEqual([]);
  });

  it("rejects the current proposal even once Live has moved on, since a rejection never writes Live", async () => {
    openSimulation(twin);
    const simulation = useTwinStore.getState().simulation!;
    twin.update((state) => patchProduct(state, "P002", { shelf_quantity: 9 }));
    const live = twin.current();
    pushed.length = 0;

    const result = await createMemoryReviewer(twin)(simulation, REVIEW_DECISION.Reject);
    expect(result).toMatchObject({ status: SIMULATION_STATUS.Rejected, verdict: null, reason_code: null });
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(twin.current()).toEqual(live);
    expect(pushed).toEqual([]);
  });

  it("answers REFRESH_REQUIRED to an accept of a replaced proposal, and commits nothing", async () => {
    const before = twin.current();
    openSimulation(twin);
    const reviewed = useTwinStore.getState().simulation!;
    const replaced = replaceProposal(reviewed);

    const result = await createMemoryReviewer(twin)(reviewed, REVIEW_DECISION.Approve);
    expect(result).toMatchObject({
      status: SIMULATION_STATUS.Evaluated,
      verdict: GUARD_VERDICT.RefreshRequired,
      reason_code: REVIEW_REASON.ProposalChanged,
      live_context_version: null,
    });
    expect(useTwinStore.getState().simulation).toBe(replaced);
    expect(twin.current()).toEqual(before);
    expect(pushed).toEqual([]);
  });
});
