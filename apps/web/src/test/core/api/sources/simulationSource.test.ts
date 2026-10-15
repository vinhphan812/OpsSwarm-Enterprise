import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSimulationSource, isNewerSimulation } from "@/core/api/sources/simulationSource";
import { parseSimulation } from "@/core/api/validate";
import { SIMULATION_STATUS } from "@/enums/simulation.enum";
import { simulationOf, DEMO_ACTIONS } from "@/fixtures/demo/simulation";
import { sampleStoreState } from "@/test/sampleState";
import type { RetailTwinClient } from "@/types/api.type";
import type { Simulation, SimulationsResponse } from "@/types/simulation.type";

const ACTIONS = [{ type: "change_facings", sku: "P001", facings: 5 }] as typeof DEMO_ACTIONS;
const run = (id = "sim-001", change: Partial<Simulation> = {}): Simulation => ({
  ...simulationOf(sampleStoreState(), ACTIONS, id),
  ...change,
});
const listOf = (...runs: Simulation[]): SimulationsResponse => ({
  simulations: runs.map(({ simulation_id, store_id, base_context_version, status }) => ({
    simulation_id,
    store_id,
    base_context_version,
    status,
  })),
});

function fakeClient(
  simulations: RetailTwinClient["simulations"],
  simulation: RetailTwinClient["simulation"],
  candidates: RetailTwinClient["candidates"] = vi.fn().mockResolvedValue({ candidates: [] }),
): RetailTwinClient {
  return {
    health: vi.fn(),
    store: vi.fn(),
    inventory: vi.fn(),
    revenue: vi.fn(),
    promotions: vi.fn(),
    simulations,
    simulation,
    candidates,
    reviewSimulation: vi.fn(),
  };
}

describe("parseSimulation", () => {
  it("accepts a run and checks its proposed state like GET /store", () => {
    const raw = run();
    raw.state.products.push({ ...raw.state.products[0], sku: "BAD", slot_id: null } as never);
    const parsed = parseSimulation(raw);
    expect(parsed.simulation_id).toBe("sim-001");
    expect(parsed.state.products.map((product) => product.sku)).not.toContain("BAD");
  });

  it("rejects a payload that breaks the contract", () => {
    expect(() => parseSimulation(null)).toThrow("not an object");
    expect(() => parseSimulation({ ...run(), base_context_version: "" })).toThrow("missing base_context_version");
    expect(() => parseSimulation({ ...run(), status: "done" })).toThrow("invalid status");
    expect(() => parseSimulation({ ...run(), actions: [{ type: "teleport", sku: "P001" }] })).toThrow("invalid actions");
    expect(() => parseSimulation({ ...run(), store_id: "store-999" })).toThrow("invalid state.store_id");
    expect(() => parseSimulation({ ...run(), state: { products: [] } })).toThrow("missing store_id");
  });
});

describe("isNewerSimulation", () => {
  it("takes another run, another status or a newer proposal, and drops older or repeated reads", () => {
    const base = run();
    const newer = run("sim-001", { state: { ...base.state, context_version: "store-001:v99" } });
    expect(isNewerSimulation(base, null)).toBe(true);
    expect(isNewerSimulation(run("sim-002"), base)).toBe(true);
    expect(isNewerSimulation(run("sim-001", { status: SIMULATION_STATUS.Pending }), base)).toBe(true);
    expect(isNewerSimulation(newer, base)).toBe(true);
    expect(isNewerSimulation(base, newer)).toBe(false);
    expect(isNewerSimulation(run(), base)).toBe(false);
  });
});

describe("simulationSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads the open run right away, delivers it once, and stops on unsubscribe", async () => {
    const simulations = vi.fn<RetailTwinClient["simulations"]>().mockResolvedValue(listOf(run()));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(run());
    const onSimulation = vi.fn();
    const unsubscribe = createSimulationSource(fakeClient(simulations, simulation), 1000).subscribe(onSimulation);

    await vi.advanceTimersByTimeAsync(2500);
    expect(simulation).toHaveBeenCalledWith("sim-001");
    expect(onSimulation).toHaveBeenCalledTimes(1);
    expect(onSimulation).toHaveBeenCalledWith(expect.objectContaining({ simulation_id: "sim-001" }), expect.any(Array));

    unsubscribe();
    await vi.advanceTimersByTimeAsync(5000);
    expect(simulations).toHaveBeenCalledTimes(3);
  });

  it("skips runs that are no longer open, and delivers null once the run closes", async () => {
    const committed = run("sim-000", { status: SIMULATION_STATUS.Committed });
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(committed, run()))
      .mockResolvedValue(listOf(committed));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(run());
    const onSimulation = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation), 1000).subscribe(onSimulation);

    await vi.advanceTimersByTimeAsync(2500);
    expect(simulation).toHaveBeenCalledTimes(1);
    expect(onSimulation.mock.calls.map(([next]) => next?.simulation_id ?? null)).toEqual(["sim-001", null]);
  });

  it("fetches candidates together with the open simulation and clears stale candidates on run change/closure", async () => {
    const run1 = run("sim-001");
    const run2 = run("sim-002");
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(run1))
      .mockResolvedValueOnce(listOf(run2))
      .mockResolvedValueOnce({ simulations: [] });
    const simulation = vi
      .fn<RetailTwinClient["simulation"]>()
      .mockResolvedValueOnce(run1)
      .mockResolvedValueOnce(run2);
    const candidates = vi
      .fn<RetailTwinClient["candidates"]>()
      .mockResolvedValueOnce({
        candidates: [
          {
            candidate_id: "cand-1",
            simulation_id: "sim-001",
            proposed_actions: ACTIONS,
            state: run1.state,
            kpis: [],
            evaluator_version: "v1",
            provenance: "test provenance",
          },
        ],
      })
      .mockResolvedValueOnce({ candidates: [] });

    const onUpdate = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation, candidates), 1000).subscribe(onUpdate);

    await vi.advanceTimersByTimeAsync(1500);
    expect(candidates).toHaveBeenCalledWith("sim-001");
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ simulation_id: "sim-001" }),
      expect.arrayContaining([expect.objectContaining({ candidate_id: "cand-1", provenance: "test provenance" })])
    );

    // Advance to sim-002
    await vi.advanceTimersByTimeAsync(1000);
    expect(candidates).toHaveBeenCalledWith("sim-002");

    // Advance to closure
    await vi.advanceTimersByTimeAsync(1000);
    expect(onUpdate).toHaveBeenLastCalledWith(null, []);
  });

  it("keeps the last run on a failed or unreadable read, and waits longer up to the cap", async () => {
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(run()))
      .mockRejectedValueOnce(new Error("404"))
      .mockRejectedValueOnce(new Error("404"))
      .mockResolvedValue(listOf(run()));
    const simulation = vi
      .fn<RetailTwinClient["simulation"]>()
      .mockResolvedValueOnce(run())
      .mockResolvedValue({ broken: true } as never);
    const onSimulation = vi.fn();
    const onError = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation), 1000, 3000).subscribe(onSimulation, onError);

    await vi.advanceTimersByTimeAsync(0); // first read
    await vi.advanceTimersByTimeAsync(1000); // fails, waits 2000
    await vi.advanceTimersByTimeAsync(2000); // fails, waits 3000 (cap)
    expect(simulations).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(2999);
    expect(simulations).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // unreadable run
    expect(onError).toHaveBeenCalledTimes(3);
    expect(onSimulation).toHaveBeenCalledTimes(1);
  });

  it("calls onRead after every good read, changed or not, and not after a failed one", async () => {
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(run()))
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValue(listOf(run()));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(run());
    const onUpdate = vi.fn();
    const onError = vi.fn();
    const onRead = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation), 1000).subscribe(onUpdate, onError, onRead);

    await vi.advanceTimersByTimeAsync(0);
    expect(onRead).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000); // fails
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onRead).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000); // same run again: no update, but a good read
    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onRead).toHaveBeenCalledTimes(2);
  });

  it("parses nested state contract and detects updated candidate KPIs/provenance or mismatched simulation_id", async () => {
    const r = run("sim-001");
    // Nested state contract: { store: StoreResponse, context_version: string }
    const nestedSim = {
      ...r,
      state: { store: r.state, context_version: r.state.context_version },
    };
    const simulations = vi.fn<RetailTwinClient["simulations"]>().mockResolvedValue(listOf(r));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(nestedSim as never);

    const cand1 = {
      candidate_id: "cand-1",
      simulation_id: "sim-001",
      proposed_actions: ACTIONS,
      state: { store: r.state, context_version: r.state.context_version },
      kpis: [{ name: "Revenue", value: 100, unit: "$", source: "v1" }],
      evaluator_version: "v1",
      provenance: "prov-1",
    };
    const cand1Updated = {
      ...cand1,
      kpis: [{ name: "Revenue", value: 200, unit: "$", source: "v1" }],
      provenance: "prov-2",
    };
    const candWrongSim = {
      ...cand1,
      candidate_id: "cand-wrong",
      simulation_id: "sim-other",
    };

    const candidates = vi
      .fn<RetailTwinClient["candidates"]>()
      .mockResolvedValueOnce({ candidates: [cand1, candWrongSim] as never })
      .mockResolvedValueOnce({ candidates: [cand1Updated, candWrongSim] as never });

    const onUpdate = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation, candidates), 1000).subscribe(onUpdate);

    await vi.advanceTimersByTimeAsync(1500);
    // Should filter out candWrongSim and successfully parse nested state
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ simulation_id: "sim-001" }),
      expect.arrayContaining([expect.objectContaining({ candidate_id: "cand-1", provenance: "prov-1" })])
    );
    expect(onUpdate.mock.calls[0][1]).toHaveLength(1);

    // Advance to poll second time with updated KPIs/provenance on same candidate ID
    await vi.advanceTimersByTimeAsync(1000);
    expect(onUpdate).toHaveBeenCalledTimes(2);
    expect(onUpdate.mock.calls[1][1]).toEqual([
      expect.objectContaining({ candidate_id: "cand-1", provenance: "prov-2" }),
    ]);
  });
});
